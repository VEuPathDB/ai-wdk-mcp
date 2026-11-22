"""Phyletic code lookup, and the binding the two species parameters derive."""

import re
from collections.abc import Mapping, Sequence
from typing import cast

from pydantic import BaseModel, Field, JsonValue
from veupathdb import JSONObject, get_logger
from veupathdb.domain import SearchContext
from veupathdb.domain.parameters import (
    NO_CONSTRAINT_PATTERN,
    PHYLETIC_EXPRESSION_PARAM,
    PHYLETIC_LIST_PARAMS,
    SHOWN_CANDIDATES,
    PhyleticBinding,
    PhyleticNode,
    PhyleticTree,
    PhyleticUnresolved,
    VocabOption,
    derive_binding,
    entry_name,
    rank_entries,
)
from veupathdb.errors import (
    ValidationError,
    VEuPathDBError,
    VEuPathDBErrorCode,
)
from veupathdb.wdk import (
    WDKParameter,
    phyletic_tree_of,
    resolve_record_type,
)

from veupathdb_mcp.catalog.discovery_service import (
    get_discovery_service,
)
from veupathdb_mcp.catalog.param_discovery import fetch_search_details
from veupathdb_mcp.catalog.param_formatting import PHYLETIC_LISTS_FORM, ParameterInfo
from veupathdb_mcp.catalog.taxonomy import (
    ORTHOMCL_PHYLETIC_SEARCH,
    PHYLETIC_PROFILE_SEARCH,
    ortho_taxonomy,
    serves_ortho_taxonomy,
)
from veupathdb_mcp.catalog.vocab_resolve import (
    NamedVocabulary,
    ResolveContext,
    interleaved,
    ordered_terms,
)
from veupathdb_mcp.embeddings.embedder import (
    EmbeddingUnavailableError,
    get_embedder,
)
from veupathdb_mcp.tool_errors import ToolErrorPayload, tool_error

logger = get_logger(__name__)

# The tree holds hundreds of entries, so the response returns only the best matches.
_MAX_TREE_MATCHES = 20

PhyleticProposals = Mapping[str, str | None]

LOOKUP_HINT = (
    "Put a code or its label in included_species (an ortholog must be present) "
    "or in excluded_species (it must be absent). A code with leaf=false is a "
    f"clade. {PHYLETIC_LISTS_FORM}"
)

EXPRESSION_LOOKUP_HINT = (
    f"Pass these codes to build_phyletic_expression, which writes "
    f"{PHYLETIC_EXPRESSION_PARAM} from them. A code with leaf=true is one genome (one "
    "proteome): several strains of one species are several genomes, grouped under "
    "species. A code with leaf=false is a clade, and genomes is the number of genomes "
    "under it. A clade is only what its label names, so a genus with no clade of its "
    "own is the list of its genome codes."
)


class PhyleticUnresolvedProposal(BaseModel):
    """Why a pair of species lists binds nothing, and the entries nearest to them."""

    unresolved: PhyleticUnresolved
    nearest: dict[str, list[VocabOption]] = Field(default_factory=dict)
    stated: dict[str, str] = Field(default_factory=dict)

    def unknown_by_list(self) -> list[tuple[str, list[str]]]:
        return [
            (name, terms)
            for name, terms in (
                ("included_species", self.unresolved.included_unknown),
                ("excluded_species", self.unresolved.excluded_unknown),
            )
            if terms
        ]


class PhyleticTreeUnread(BaseModel):
    orthomcl_elsewhere: bool


class PhyleticNoSelection(BaseModel):
    """Neither list selects a species, so the criterion constrains nothing.

    The bare wildcard is a valid pattern and returns every gene of the chosen
    organisms, which reads as a phyletic answer and is not one.
    """


PhyleticDerivation = PhyleticBinding | PhyleticUnresolvedProposal | PhyleticNoSelection


class PhyleticListError(ValidationError):
    def __init__(
        self,
        refused: PhyleticUnresolvedProposal | PhyleticNoSelection | PhyleticTreeUnread,
    ) -> None:
        self.refused = refused
        match refused:
            case PhyleticUnresolvedProposal():
                rows = _list_rows(refused)
            case PhyleticNoSelection():
                rows = _pattern_rows(
                    "included_species and excluded_species select no species, so "
                    "profile_pattern states no criterion. Name what must have an "
                    "ortholog and what must not."
                )
            case PhyleticTreeUnread(orthomcl_elsewhere=elsewhere):
                rows = _pattern_rows(_tree_unread(elsewhere=elsewhere))
        super().__init__(
            title="The species parameters derive no profile_pattern",
            detail="\n".join(str(row["detail"]) for row in rows),
            errors=list(rows),
        )


def _tree_unread(*, elsewhere: bool) -> str:
    unread = (
        "The site's species tree does not read: its phyletic_indent_map and "
        "phyletic_term_map give no tree, so included_species and excluded_species "
        "derive no profile_pattern, and restating them cannot fix it."
    )
    if not elsewhere:
        return unread
    return (
        f"{unread} Take another route: OrthoMCL's Phyletic Pattern search "
        f"({ORTHOMCL_PHYLETIC_SEARCH}) states the pattern as a phyletic_expression "
        "against OrthoMCL's own tree."
    )


def _pattern_rows(detail: str) -> list[JSONObject]:
    return [{"param": "profile_pattern", "detail": detail}]


def _list_rows(refused: PhyleticUnresolvedProposal) -> list[JSONObject]:
    unresolved = refused.unresolved
    rows: list[JSONObject] = []
    for name, unknown in (
        ("included_species", unresolved.included_unknown),
        ("excluded_species", unresolved.excluded_unknown),
    ):
        faults = [f"{name} names no entry {unknown}"] if unknown else []
        if unresolved.conflicts:
            other = (
                "excluded_species" if name == "included_species" else "included_species"
            )
            faults.append(f"{name} and {other} both name {unresolved.conflicts}")
        near = ", ".join(entry_name(entry) for entry in refused.nearest.get(name, []))
        if near:
            faults.append(f"Nearest entries: {near}")
        if faults:
            rows.append(
                {
                    "param": name,
                    "value": refused.stated.get(name),
                    "detail": f"{'. '.join(faults)}.",
                }
            )
    return rows


def is_phyletic_sheet(infos: list[ParameterInfo]) -> bool:
    """Whether this sheet belongs to a phyletic search.

    The sheet drops the two structural maps, so the pattern and the two lists are
    the names that identify the search here. What the call proposes is not part
    of the signature: naming neither list is itself an empty selection.
    """
    names = {info.name for info in infos}
    return frozenset(PhyleticBinding.model_fields) <= names


def _ranked_entries(tree: PhyleticTree, unknown: Sequence[str]) -> list[VocabOption]:
    """The entries ranked closest to the terms that named nothing."""
    options = tree.labels()
    return interleaved(
        [rank_entries(options, term, SHOWN_CANDIDATES) for term in unknown],
        _value,
        SHOWN_CANDIDATES,
    )


def _value(entry: VocabOption) -> str:
    return entry.value


async def phyletic_refusal(
    refused: PhyleticUnresolvedProposal | PhyleticNoSelection | None,
    declarations: Sequence[WDKParameter],
    site: ResolveContext | str,
) -> PhyleticListError:
    """The refusal of a derivation that binds no pattern on ``site``; a
    ``ResolveContext`` also leads the nearest entries by a Decisions choice."""
    match site:
        case ResolveContext(site_id=site_id) as about:
            return await _ordered(await _refusal(refused, site_id), declarations, about)
        case str():
            return await _refusal(refused, site)


async def _refusal(
    refused: PhyleticUnresolvedProposal | PhyleticNoSelection | None, site_id: str
) -> PhyleticListError:
    match refused:
        case None:
            elsewhere = not await serves_ortho_taxonomy(site_id)
            return PhyleticListError(PhyleticTreeUnread(orthomcl_elsewhere=elsewhere))
        case _:
            return PhyleticListError(refused)


async def _ordered(
    refusal: PhyleticListError,
    declarations: Sequence[WDKParameter],
    about: ResolveContext,
) -> PhyleticListError:
    tree = phyletic_tree_of(list(declarations))
    match refusal.refused:
        case PhyleticUnresolvedProposal() as proposal if tree is not None:
            displays = {d.name: d.display_name or d.name for d in declarations}
            labels = tree.labels()
            lists = proposal.unknown_by_list()
            asked = [
                (NamedVocabulary(display=displays.get(name, name), options=labels), t)
                for name, terms in lists
                for t in terms
            ]
            led = iter(await ordered_terms(about, asked))
            nearest = {
                name: interleaved([next(led) for _ in terms], _value, SHOWN_CANDIDATES)
                for name, terms in lists
            }
            return PhyleticListError(proposal.model_copy(update={"nearest": nearest}))
        case _:
            return refusal


def derive_phyletic_overrides(
    definition_params: list[WDKParameter], proposals: PhyleticProposals
) -> PhyleticDerivation | None:
    """The three parameter values a proposal of the two species lists states.

    ``None`` means the search's species tree does not read. A list left null, and a list the call never names, both count as
    the empty selection, and two empty selections state no criterion at all.
    """
    tree = phyletic_tree_of(definition_params)
    if tree is None:
        return None
    if not PHYLETIC_LIST_PARAMS & proposals.keys():
        return PhyleticNoSelection()
    binding = derive_binding(
        tree,
        proposals.get("included_species") or "",
        proposals.get("excluded_species") or "",
    )
    if isinstance(binding, PhyleticUnresolved):
        proposal = PhyleticUnresolvedProposal(
            stated={name: text for name, text in proposals.items() if text is not None},
            unresolved=binding,
        )
        return proposal.model_copy(
            update={
                "nearest": {
                    name: _ranked_entries(tree, terms)
                    for name, terms in proposal.unknown_by_list()
                }
            }
        )
    if binding.profile_pattern == NO_CONSTRAINT_PATTERN:
        return PhyleticNoSelection()
    return binding


def _named_nodes(tree: PhyleticTree, query: str) -> list[PhyleticNode]:
    known = {word for node in tree.nodes() for word in _words(node.label)}
    asked = [word for word in _words(query) if word in known]
    if not asked:
        return []
    return [
        node
        for node in tree.nodes()
        if all(word in _words(node.label) for word in asked)
    ]


async def _match_phyletic_entries(
    tree: PhyleticTree, query: str
) -> tuple[list[JSONObject], list[JSONObject]]:
    """The matches and the species they name.

    The matches are every node whose label holds each query word some label holds,
    in tree order, then the nodes nearest the query by semantic similarity up to
    the cap. A list of strains is only usable whole, so a label match is never
    capped. The species group the genomes of the label matches only.
    """
    nodes = list(tree.nodes())
    if not nodes:
        return [], []
    named = _named_nodes(tree, query)
    held = {node.code for node in named}
    ranked = await _rank_by_semantic_similarity(query, nodes)
    nearest = [node for node in ranked if node.code not in held]
    matches: list[JSONObject] = [
        {
            "code": node.code,
            "label": node.label,
            "leaf": not node.clade,
            "genomes": len(tree.genomes_under([node.code])),
        }
        for node in [*named, *nearest[: max(_MAX_TREE_MATCHES - len(named), 0)]]
    ]
    genomes = [node.code for node in named if not node.clade]
    species: list[JSONObject] = [
        {"species": group.species, "genomes": list(group.genomes)}
        for group in tree.species_groups(genomes)
    ]
    return matches, species


def _words(text: str) -> set[str]:
    return set(re.findall(r"\w+", text.casefold()))


async def _rank_by_semantic_similarity(
    query: str,
    candidates: list[PhyleticNode],
) -> list[PhyleticNode]:
    """Ranks the candidates by cosine similarity to the query.

    An unreachable embedding API leaves the candidates in tree order.
    """
    embedder = get_embedder()
    try:
        query_vector = await embedder.embed_query(query)
        label_vectors = await embedder.embed_documents(
            [node.label for node in candidates],
        )
    except EmbeddingUnavailableError as exc:
        logger.warning(
            "Phyletic ranking unavailable, returning unranked results",
            error=str(exc),
            query=query,
            num_candidates=len(candidates),
        )
        return candidates
    scored = sorted(
        zip(candidates, label_vectors, strict=True),
        key=lambda pair: -_dot(query_vector, pair[1]),
    )
    return [candidate for candidate, _ in scored]


def _dot(left: list[float], right: list[float]) -> float:
    """Cosine similarity of two unit vectors."""
    return sum(a * b for a, b in zip(left, right, strict=True))


async def genome_names(site_id: str) -> dict[str, str]:
    tree = await ortho_taxonomy(site_id)
    if tree is None:
        return {}
    return {node.code: node.label for node in tree.nodes() if not node.clade}


async def lookup_phyletic_codes(
    site_id: str,
    record_type: str,
    query: str,
) -> JSONObject | ToolErrorPayload:
    """Searches the phyletic species and clade codes by name: OrthoMCL's taxonomy on
    a site that serves it, and the profile search's tree elsewhere."""
    try:
        if await serves_ortho_taxonomy(site_id):
            tree = await ortho_taxonomy(site_id)
            hint = EXPRESSION_LOOKUP_HINT
        else:
            record_types = await get_discovery_service().get_record_types(site_id)
            resolved = resolve_record_type(record_types, record_type) or record_type
            response, _ = await fetch_search_details(
                SearchContext(site_id, resolved, PHYLETIC_PROFILE_SEARCH),
                record_types=record_types,
            )
            tree = phyletic_tree_of(response.search_data.parameters or [])
            hint = LOOKUP_HINT
        matches, species = await _match_phyletic_entries(
            PhyleticTree() if tree is None else tree, query
        )

        return {
            "query": query,
            "matches": cast("JsonValue", matches),
            "species": cast("JsonValue", species),
            "total": len(matches),
            "hint": hint,
        }
    except VEuPathDBError as exc:
        return tool_error(
            VEuPathDBErrorCode.INTERNAL_ERROR,
            f"Failed to look up phyletic codes: {exc}",
        )

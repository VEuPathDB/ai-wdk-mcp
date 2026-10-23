"""Phyletic code lookup, and the binding the two species lists derive."""

import re
from collections.abc import Mapping, Sequence
from typing import cast

from pydantic import BaseModel, Field, JsonValue
from veupathdb import JSONObject, get_logger
from veupathdb.domain import SearchContext
from veupathdb.domain.parameters import (
    MAX_NEAREST_ENTRIES,
    NO_CONSTRAINT_PATTERN,
    PHYLETIC_EXPRESSION_PARAM,
    PHYLETIC_EXPRESSION_SEARCH,
    PHYLETIC_LIST_PARAMS,
    PhyleticBinding,
    PhyleticNode,
    PhyleticTree,
    PhyleticUnresolved,
    derive_binding,
    nearest_entries,
)
from veupathdb.errors import (
    ValidationError,
    VEuPathDBError,
    VEuPathDBErrorCode,
    param_message_rows,
)
from veupathdb.wdk import (
    WDKParameter,
    WDKRecordType,
    phyletic_tree_of,
    resolve_record_type,
)

from veupathdb_mcp.catalog.discovery_service import (
    get_discovery_service,
)
from veupathdb_mcp.catalog.param_discovery import fetch_search_details
from veupathdb_mcp.catalog.param_formatting import ParameterInfo
from veupathdb_mcp.catalog.taxonomy import ortho_taxonomy
from veupathdb_mcp.embeddings.embedder import (
    EmbeddingUnavailableError,
    get_embedder,
)
from veupathdb_mcp.tool_errors import ToolErrorPayload, tool_error

logger = get_logger(__name__)

# The tree holds hundreds of entries, so the response returns only the best matches.
_MAX_TREE_MATCHES = 20

PhyleticProposals = Mapping[str, str | list[str] | None]

LOOKUP_HINT = (
    "Put a code or its label in included_species (an ortholog must be present) "
    "or in excluded_species (it must be absent). A code with leaf=false is a "
    "clade and selects every species under it. profile_pattern is derived from "
    "the two lists; never write it."
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
    nearest: list[str] = Field(default_factory=list)


class PhyleticNoSelection(BaseModel):
    """Neither list selects a species, so the criterion constrains nothing.

    The bare wildcard is a valid pattern and returns every gene of the chosen
    organisms, which reads as a phyletic answer and is not one.
    """


PhyleticDerivation = PhyleticBinding | PhyleticUnresolvedProposal | PhyleticNoSelection


class PhyleticListError(ValidationError):
    def __init__(
        self, refused: PhyleticUnresolvedProposal | PhyleticNoSelection | None
    ) -> None:
        self.refused = refused
        match refused:
            case PhyleticUnresolvedProposal(unresolved=unresolved, nearest=nearest):
                named = [
                    f"{name} names no entry {terms}"
                    for name, terms in (
                        ("included_species", unresolved.included_unknown),
                        ("excluded_species", unresolved.excluded_unknown),
                    )
                    if terms
                ]
                if unresolved.conflicts:
                    named.append(f"both lists name {unresolved.conflicts}")
                detail = f"{'; '.join(named)}. Nearest entries: {nearest}."
            case PhyleticNoSelection():
                detail = (
                    "included_species and excluded_species select no species, so "
                    "profile_pattern states no criterion. Name what must have an "
                    "ortholog and what must not."
                )
            case None:
                detail = (
                    "profile_pattern is derived from included_species and "
                    "excluded_species against the search's published parameters, "
                    "and the call passed none."
                )
        super().__init__(
            title="The species lists derive no profile_pattern",
            detail=detail,
            errors=param_message_rows({"profile_pattern": [detail]}),
        )


def is_phyletic_sheet(infos: list[ParameterInfo]) -> bool:
    """Whether this sheet belongs to a phyletic search.

    The sheet drops the two structural maps, so the pattern and the two lists are
    the names that identify the search here. What the call proposes is not part
    of the signature: naming neither list is itself an empty selection.
    """
    names = {info.name for info in infos}
    return frozenset(PhyleticBinding.model_fields) <= names


def _nearest_entries(tree: PhyleticTree, unknown: Sequence[str]) -> list[str]:
    """The codes and labels closest to the terms that named nothing."""
    options = tree.labels()
    found: list[str] = []
    for term in unknown:
        for match in nearest_entries(options, term, MAX_NEAREST_ENTRIES):
            if match not in found:
                found.append(match)
    return found[:MAX_NEAREST_ENTRIES]


def derive_phyletic_overrides(
    definition_params: list[WDKParameter], proposals: PhyleticProposals
) -> PhyleticDerivation | None:
    """The three parameter values a proposal of the two species lists states.

    ``None`` means the derivation does not apply, because the search is not
    phyletic. A list left null, and a list the call never names, both count as
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
        return PhyleticUnresolvedProposal(
            unresolved=binding,
            nearest=_nearest_entries(
                tree, [*binding.included_unknown, *binding.excluded_unknown]
            ),
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


async def _takes_an_expression(
    site_id: str, record_types: Sequence[WDKRecordType]
) -> bool:
    """Whether the site's phyletic search is OrthoMCL's expression search."""
    discovery = get_discovery_service()
    for listed in record_types:
        searches = await discovery.get_searches(site_id, listed.url_segment)
        if any(search.url_segment == PHYLETIC_EXPRESSION_SEARCH for search in searches):
            return True
    return False


async def genome_names(site_id: str) -> dict[str, str]:
    discovery = get_discovery_service()
    if not await _takes_an_expression(
        site_id, await discovery.get_record_types(site_id)
    ):
        return {}
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
    a site with the expression search, and the profile search's tree elsewhere."""
    try:
        discovery = get_discovery_service()
        record_types = await discovery.get_record_types(site_id)
        if await _takes_an_expression(site_id, record_types):
            tree = await ortho_taxonomy(site_id)
            hint = EXPRESSION_LOOKUP_HINT
        else:
            resolved = resolve_record_type(record_types, record_type) or record_type
            response, _ = await fetch_search_details(
                SearchContext(site_id, resolved, "GenesByOrthologPattern"),
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

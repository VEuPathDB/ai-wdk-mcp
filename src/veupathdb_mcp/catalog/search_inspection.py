"""Reads one WDK search: its overview, and one parameter's options.

Every function takes a site and its arguments by value, so the same code
answers an in-process tool call and a remote one.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from difflib import get_close_matches

from veupathdb.domain.parameters import (
    ParamValue,
    WDKTreeBoxVocabNode,
    coerce_context_values,
)
from veupathdb.errors import WDKError
from veupathdb.wdk import (
    WDKBaseParameter,
    WDKParameter,
    WDKSearch,
    encode_wdk_params,
    get_wdk_client,
)

from veupathdb_mcp.catalog.overview_formatting import (
    SearchOverviewResult,
    format_search_overview,
)
from veupathdb_mcp.catalog.param_formatting import (
    GetParameterOptionsResult,
    ParameterNotOnSearch,
    ParentContextRequired,
    format_param_info_typed,
    format_typed_param,
    phyletic_options_for,
)
from veupathdb_mcp.catalog.search_context import (
    get_search_params_under_context,
)
from veupathdb_mcp.catalog.searches import (
    get_raw_searches,
    read_search_definition,
    resolve_search_record_type,
)

_SEARCH_NOT_FOUND_STATUS = 404


def _did_you_mean(
    candidate: str,
    valid: list[str],
    *,
    kind: str,
    search_name: str | None = None,
) -> str:
    """Build a message that lists valid candidates to copy verbatim."""
    suggestions = get_close_matches(candidate, valid, n=5, cutoff=0.3)
    where = f" on search {search_name!r}" if search_name else ""
    parts = [f"{kind} {candidate!r} does not exist{where}."]
    if suggestions:
        parts.append(f"Did you mean: {suggestions}?")
    parts.append(f"Valid {kind} values: {sorted(valid)}.")
    return " ".join(parts)


class UnknownSearchError(Exception):
    """A search name the site's catalog does not carry."""

    def __init__(self, search_name: str, valid_search_names: list[str]) -> None:
        self.search_name = search_name
        self.valid_search_names = valid_search_names
        self.guidance = _did_you_mean(search_name, valid_search_names, kind="search")
        super().__init__(self.guidance)


@dataclass(frozen=True, slots=True)
class VocabNarrowing:
    """How one parameter read cuts a vocabulary down to what travels.

    ``query`` keeps the entries that carry the text. ``organism_hints`` reorders
    a tree so the branches naming those organisms render before the cap.
    """

    query: str | None = None
    organism_hints: Sequence[str] = ()


@dataclass(frozen=True, slots=True)
class SearchInspection:
    """One WDK read of a search: the formatted overview and the definition."""

    record_type: str
    definition: WDKSearch
    overview: SearchOverviewResult


def _auto_resolved_record_type(record_type: str | None) -> str | None:
    """Drop the 'gene' record type so the record type is auto-resolved.

    In WDK, gene searches live under the 'transcript' record type.
    """
    if record_type == "gene":
        return None
    return record_type


def _entry_matches(term: str, display: str, query: str) -> bool:
    return query in term.casefold() or query in display.casefold()


def _matching_branches(
    node: WDKTreeBoxVocabNode,
    query: str,
) -> WDKTreeBoxVocabNode | None:
    """The node when it or a descendant matches, carrying only those branches.

    A node that matches keeps its whole subtree, because its children are the
    submittable terms under it.
    """
    if _entry_matches(node.data.term, node.data.display, query):
        return node
    kept = [
        branch
        for branch in (_matching_branches(child, query) for child in node.children)
        if branch is not None
    ]
    if not kept:
        return None
    return node.model_copy(update={"children": kept})


def _prioritized_branches(
    node: WDKTreeBoxVocabNode,
    hints: Sequence[str],
) -> WDKTreeBoxVocabNode:
    """Reorder children so branches matching a hint come first, at every depth."""
    folded = [hint.casefold() for hint in hints if hint]
    if not folded:
        return node

    def reaches(candidate: WDKTreeBoxVocabNode) -> bool:
        if any(
            _entry_matches(candidate.data.term, candidate.data.display, hint)
            for hint in folded
        ):
            return True
        return any(reaches(child) for child in candidate.children)

    def reorder(candidate: WDKTreeBoxVocabNode) -> WDKTreeBoxVocabNode:
        if not candidate.children:
            return candidate
        matching: list[WDKTreeBoxVocabNode] = []
        rest: list[WDKTreeBoxVocabNode] = []
        for child in candidate.children:
            (matching if reaches(child) else rest).append(reorder(child))
        return candidate.model_copy(update={"children": matching + rest})

    return reorder(node)


def _filter_vocab(param: WDKParameter, query: str) -> WDKParameter:
    """Filter a parameter vocabulary by a case-insensitive substring.

    A list keeps the entries whose term or label carries the text; a tree keeps
    the branches that reach one.
    """
    vocab = param.vocabulary
    if vocab is None:
        return param
    q = query.casefold()

    if isinstance(vocab, WDKTreeBoxVocabNode):
        pruned = _matching_branches(vocab, q)
        return param.model_copy(
            update={"vocabulary": pruned or vocab.model_copy(update={"children": []})},
        )

    kept = [term for term in vocab if _entry_matches(term.term, term.display, q)]
    return param.model_copy(update={"vocabulary": kept})


def _prioritize_organisms(
    param: WDKParameter,
    hints: Sequence[str],
) -> WDKParameter:
    vocab = param.vocabulary
    if not hints or not isinstance(vocab, WDKTreeBoxVocabNode):
        return param
    return param.model_copy(
        update={"vocabulary": _prioritized_branches(vocab, hints)},
    )


def _unbound_parents(
    all_params: list[WDKParameter],
    parameter_id: str,
    bound: Mapping[str, ParamValue],
) -> list[str]:
    """The parents of `parameter_id` that carry no value yet.

    A dependent vocabulary is generated under its parents, so a read without
    them answers about the search's default parent rather than the one meant.
    """
    return sorted(
        p.name
        for p in all_params
        if parameter_id in (p.dependent_params or []) and p.name not in bound
    )


async def inspect_search(
    site_id: str,
    search_name: str,
    *,
    record_type: str | None = None,
    query: str | None = None,
) -> SearchInspection:
    """Read one search and format it. ``query`` ranks an oversized vocabulary."""
    rt = await resolve_search_record_type(
        site_id, search_name, _auto_resolved_record_type(record_type)
    )
    try:
        search = await read_search_definition(site_id, rt, search_name)
    except WDKError as exc:
        if exc.status != _SEARCH_NOT_FOUND_STATUS:
            raise
        valid = [s.url_segment for s in await get_raw_searches(site_id, rt)]
        raise UnknownSearchError(search_name, [name for name in valid if name]) from exc

    overview = format_search_overview(
        definition=search,
        record_type=rt,
        infos=format_param_info_typed(search.parameters or []),
        query=query or "",
    )
    return SearchInspection(record_type=rt, definition=search, overview=overview)


async def read_parameter_options(
    site_id: str,
    search_name: str,
    parameter_id: str,
    *,
    record_type: str | None = None,
    context_values: Mapping[str, object] | None = None,
    narrowing: VocabNarrowing | None = None,
) -> GetParameterOptionsResult:
    """Read one parameter's vocabulary under the parent values supplied.

    ``narrowing`` cuts a vocabulary too large to travel whole.
    """
    narrow = narrowing or VocabNarrowing()
    context = coerce_context_values(dict(context_values)) if context_values else {}
    rt = await resolve_search_record_type(
        site_id, search_name, _auto_resolved_record_type(record_type)
    )
    result = await get_search_params_under_context(
        get_wdk_client(site_id),
        rt,
        search_name,
        encode_wdk_params(context) if context else {},
    )
    all_params = result.search_data.parameters or []

    unbound = _unbound_parents(all_params, parameter_id, context)
    if unbound:
        return ParentContextRequired(
            search_name=search_name,
            parameter_id=parameter_id,
            parent_parameter_ids=unbound,
            message=(
                f"'{parameter_id}' has a different vocabulary under each value of "
                f"{', '.join(unbound)}, so there is no list to show until one is "
                f"chosen. Read {unbound[0]} first, then call this again passing "
                f"context_values={{'{unbound[0]}': '<the value you chose>'}}."
            ),
        )

    depends_on: dict[str, list[str]] = {}
    controls: dict[str, list[str]] = {}
    for p in all_params:
        base: WDKBaseParameter = p
        if base.dependent_params:
            controls[base.name] = list(base.dependent_params)
            for dep in base.dependent_params:
                depends_on.setdefault(dep, []).append(base.name)

    for p in all_params:
        if p.name == parameter_id:
            filtered = _filter_vocab(p, narrow.query) if narrow.query else p
            return format_typed_param(
                _prioritize_organisms(filtered, narrow.organism_hints),
                depends_on=depends_on,
                controls=controls,
                applied_context=context or None,
                parent_defaults={
                    other.name: other.initial_display_value
                    for other in all_params
                    if other.initial_display_value
                },
                phyletic_options=phyletic_options_for(
                    all_params, parameter_id, narrow.query
                ),
            )

    valid = [p.name for p in all_params]
    return ParameterNotOnSearch(
        search_name=search_name,
        requested_parameter_id=parameter_id,
        message=_did_you_mean(
            parameter_id,
            valid,
            kind="parameter_id",
            search_name=search_name,
        ),
        suggestions=get_close_matches(parameter_id, valid, n=5, cutoff=0.3),
        valid_parameter_ids=sorted(valid),
    )

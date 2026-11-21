"""Deterministic resolution of a WDK search's parameter dependency DAG."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from functools import partial

from pydantic import Field, JsonValue
from veupathdb.domain import SearchContext
from veupathdb.domain.parameters import (
    PHYLETIC_LIST_PARAMS,
    FilterFacets,
    FilterProposals,
    MultiPickValue,
    ParamGraph,
    ParamValue,
    PhyleticBinding,
    SinglePickValue,
    Stated,
    UnboundParameter,
    flatten_vocab,
    match_exact_option,
    read_stated_values,
    to_wire,
    wire_map,
)
from veupathdb.errors import ValidationError
from veupathdb.model import CamelModel
from veupathdb.wdk import WDKParameter, get_wdk_client

from veupathdb_mcp.catalog._param_binding import (
    OverrideMap,
    ResolvedParam,
    Unread,
    _Resolution,
    _resolve_nonfilter,
    _sole_claim,
    _VocabLedger,
)
from veupathdb_mcp.catalog._param_filters import _resolve_filter_param
from veupathdb_mcp.catalog.discovery_service import (
    get_discovery_service,
)
from veupathdb_mcp.catalog.facet_ranges import FilterReads, refuse_filter_misses
from veupathdb_mcp.catalog.param_formatting import (
    ParameterInfo,
    format_param_info_typed,
)
from veupathdb_mcp.catalog.param_intent import (
    ParamIntent,
    Provenance,
    contrast_pair_key,
    contrast_role,
)
from veupathdb_mcp.catalog.param_phyletic import (
    PhyleticListError,
    PhyleticNoSelection,
    derive_phyletic_overrides,
    is_phyletic_sheet,
)
from veupathdb_mcp.catalog.search_context import (
    get_search_params_under_context,
)
from veupathdb_mcp.catalog.site_set_params import SiteSetParameterError

_MAX_RESOLVE_DEPTH = 6


class UnknownParameterError(ValidationError):
    """An override names a parameter the search does not have."""

    def __init__(self, unknown: list[str], valid: list[str]) -> None:
        self.unknown = unknown
        self.valid = valid
        super().__init__(
            title="Unknown parameter",
            detail=(
                f"No such parameter(s) on this search: {unknown}. Valid names: {valid}."
            ),
            errors=[{"param": name} for name in unknown],
        )


def _refuse_unknown_overrides(
    infos: list[ParameterInfo], stated: Mapping[str, JsonValue]
) -> None:
    """Refuses an override that names no parameter of the search.

    The search names every parameter on the first fetch, so a name the walk would
    never read is a mistake, not a value to drop.
    """
    names = {i.name for i in infos}
    unknown = sorted(set(stated) - names)
    if unknown:
        raise UnknownParameterError(
            unknown, sorted(i.name for i in infos if i.bindable)
        )


def _refuse_hidden_overrides(
    infos: list[ParameterInfo], stated: Mapping[str, JsonValue], search_name: str
) -> None:
    for info in infos:
        if info.name in stated and info.site_set:
            raise SiteSetParameterError(info.name, search_name)


def _with_derived_phyletic(
    infos: list[ParameterInfo],
    overrides: OverrideMap,
    declarations: Sequence[WDKParameter],
) -> OverrideMap:
    if not is_phyletic_sheet(infos):
        return overrides
    if not PHYLETIC_LIST_PARAMS & overrides.keys():
        raise PhyleticListError(PhyleticNoSelection())
    lists = {
        name: to_wire(value)
        for name, value in overrides.items()
        if name in PHYLETIC_LIST_PARAMS
    }
    match derive_phyletic_overrides(list(declarations), lists):
        case PhyleticBinding() as binding:
            return {**overrides, **read_declared(declarations, binding.model_dump())}
        case refused:
            raise PhyleticListError(refused)


def _visible_slot(
    info: ParameterInfo, slot: UnboundParameter, search_name: str
) -> UnboundParameter | None:
    if info.bindable:
        return slot
    if info.param_kind != "input-step":
        raise SiteSetParameterError(info.name, search_name, unset=True)
    return None


class UnreadStatementError(ValidationError):
    """A stated name that no fetch under its parents declares."""

    def __init__(self, unread: list[str]) -> None:
        self.unread = unread
        super().__init__(
            title="Unread parameter value",
            detail=(
                f"No read under the stated parents declares {unread}, so their "
                "values cannot be read."
            ),
            errors=[{"param": name} for name in unread],
        )


def _bound(declaration: WDKParameter, read: Stated) -> ParamValue:
    """Binds a filter statement to its facets, and each pick to the term its
    entry carries."""
    options = flatten_vocab(declaration.vocabulary)
    match read:
        case FilterProposals():
            return FilterFacets.of(declaration).bind(read)
        case SinglePickValue(value=term):
            return SinglePickValue(value=match_exact_option(options, term) or term)
        case MultiPickValue(values=terms):
            return MultiPickValue(
                values=[match_exact_option(options, t) or t for t in terms]
            )
        case _:
            return read


def read_declared(
    declarations: Sequence[WDKParameter], stated: Mapping[str, JsonValue]
) -> dict[str, ParamValue]:
    declared = {d.name: d for d in declarations}
    return {
        name: _bound(declared[name], read)
        for name, read in read_stated_values(declarations, stated).items()
    }


def _waiting(
    declarations: Sequence[WDKParameter],
    stated: Mapping[str, JsonValue],
    context: dict[str, str],
) -> set[str]:
    """The names whose stated or site-set wire parents are not in the context yet."""
    parents = ParamGraph.of(declarations).wire_parents
    waited = stated.keys() | {d.name for d in declarations if d.site_set}
    return {
        d.name
        for d in declarations
        if set(parents.get(d.name, ())) & (waited - context.keys())
    }


def _read_ready(
    declarations: Sequence[WDKParameter],
    stated: Mapping[str, JsonValue],
    context: dict[str, str],
    read: Mapping[str, ParamValue],
) -> dict[str, ParamValue]:
    """Reads each stated name not yet read whose parents are in the context, under
    the declarations fetched at that context."""
    waiting = _waiting(declarations, stated, context)
    ready = [
        d
        for d in declarations
        if d.name in stated and d.name not in read and d.name not in waiting
    ]
    return read_declared(ready, stated)


def _read_pass(
    infos: list[ParameterInfo],
    declarations: Sequence[WDKParameter],
    stated: Mapping[str, JsonValue],
    context: dict[str, str],
    overrides: OverrideMap,
    *,
    first: bool,
) -> OverrideMap:
    if first:
        _refuse_unknown_overrides(infos, stated)
    read = {**overrides, **_read_ready(declarations, stated, context, overrides)}
    return _with_derived_phyletic(infos, read, declarations) if first else read


async def _refuse_misses(
    declarations: Sequence[WDKParameter],
    read: Mapping[str, ParamValue],
    context: dict[str, str],
    reads: FilterReads,
) -> None:
    parents = ParamGraph.of(declarations).wire_parents
    for declaration in declarations:
        if declaration.name in read:
            await refuse_filter_misses(
                declaration,
                read[declaration.name],
                {
                    p: context[p]
                    for p in parents.get(declaration.name, ())
                    if p in context
                },
                reads,
            )


ParamFetcher = Callable[[dict[str, str]], Awaitable[list[WDKParameter]]]


async def read_under_parents(
    fetch_at: ParamFetcher, stated: Mapping[str, JsonValue], reads: FilterReads
) -> dict[str, ParamValue]:
    """Reads each stated value under the declarations its stated and site-set parents
    give, and refuses a filter that selects nothing. A name of no parameter is
    refused before any value is read."""
    context: dict[str, str] = {}
    read: dict[str, ParamValue] = {}
    declarations = await fetch_at(context)
    _refuse_unknown_overrides(format_param_info_typed(declarations), stated)
    for _ in range(_MAX_RESOLVE_DEPTH):
        missing = stated.keys() - read.keys()
        if not missing:
            return read
        waiting = _waiting(declarations, stated, context)
        sited = {
            d.name: d.initial_display_value
            for d in declarations
            if d.site_set
            and d.initial_display_value is not None
            and d.name not in context
            and d.name not in waiting
        }
        new = _read_ready(declarations, stated, context, read)
        if not new and not sited:
            new = read_declared([d for d in declarations if d.name in missing], stated)
        if not new and not sited:
            break
        await _refuse_misses(declarations, new, context, reads)
        read |= new
        context |= sited | wire_map(new)
        if stated.keys() - read.keys():
            declarations = await fetch_at(context)
    unread = sorted(stated.keys() - read.keys())
    if unread:
        raise UnreadStatementError(unread)
    return read


def wdk_fetch_at(site_id: str, record_type: str, search_name: str) -> ParamFetcher:
    ctx = SearchContext(site_id, record_type, search_name)

    async def fetch_at(context: dict[str, str]) -> list[WDKParameter]:
        # The catalog holds the published view for the process, so every pass of
        # the walk sends the same parameter shape at the cost of one HTTP read.
        published = await get_discovery_service().get_search_details(
            ctx, expand_params=True
        )
        resp = await get_search_params_under_context(
            get_wdk_client(site_id),
            record_type,
            search_name,
            context,
            published=published,
        )
        return resp.search_data.parameters or []

    return fetch_at


class ResolvedParams(CamelModel):
    """Build-ready params, plus open slots and the required params that stay unresolved."""

    params: dict[str, ParamValue] = Field(default_factory=dict)
    provenance: dict[str, Provenance] = Field(default_factory=dict)
    open_slots: list[UnboundParameter] = Field(default_factory=list)
    unresolved_required: list[str] = Field(default_factory=list)
    # Params the request states a quantity for and nothing bound.
    unread: list[str] = Field(default_factory=list)

    def defaulted(self) -> list[str]:
        """Params holding the search default rather than a stated value."""
        return sorted(
            name
            for name, source in self.provenance.items()
            if source is Provenance.DEFAULTED
        )


def _awaits_comparator(
    info: ParameterInfo, infos: list[ParameterInfo], resolved: set[str]
) -> bool:
    """Reports whether a reference slot must wait for its comparator sibling. The
    baseline is defined by the value the comparator does not take.
    """
    if contrast_role(info) != "reference":
        return False
    # Pair on the name stem. A vocabulary signature does not match while the comparator
    # still carries its pre-parent option set, and a bare role match couples
    # unrelated pairs.
    key = contrast_pair_key(info.name)
    return any(
        other.name not in resolved
        and other.name != info.name
        and contrast_role(other) == "comparison"
        and contrast_pair_key(other.name) == key
        for other in infos
    )


def _evict_for_override(
    info: ParameterInfo,
    overrides: OverrideMap,
    *,
    ledger: _VocabLedger,
    params: dict[str, ParamValue],
    context: dict[str, str],
    seen: set[str],
) -> None:
    """Unbinds a defaulted param that holds the value this override wants, so it
    re-resolves against the claimed vocabulary."""
    if info.name not in overrides:
        return
    wanted = _sole_claim(overrides[info.name])
    if wanted is None:
        return
    evicted = ledger.release_default_holding(info, wanted, overrides)
    if evicted is None:
        return
    params.pop(evicted, None)
    context.pop(evicted, None)
    seen.discard(evicted)


def _resolution_rank(info: ParameterInfo, overrides: OverrideMap) -> tuple[int, int]:
    """Orders resolution within a pass so authoritative values claim their vocabulary
    slot first: overrides, then comparators, then the rest, then references.
    """
    role = contrast_role(info)
    role_rank = {"comparison": 0, "reference": 2}.get(role or "", 1)
    return (0 if info.name in overrides else 1, role_rank)


def _defer_to_next_pass(
    info: ParameterInfo,
    *,
    context: dict[str, str],
    resolved_this_pass: set[str],
) -> bool:
    """Reports whether to skip the param until the walk re-fetches under a new context.

    A param whose vocabulary parent is unresolved, or resolved during this pass, has a
    stale option set. The next pass fetches the real vocabulary.
    """
    depends_on = set(info.wire_parents)
    if depends_on - context.keys():
        return True
    return bool(depends_on & resolved_this_pass)


async def _outcome_for(
    info: ParameterInfo,
    infos: list[ParameterInfo],
    resolution: _Resolution,
    ledger: _VocabLedger,
    read_filter: Callable[[ParamValue], Awaitable[None]],
) -> ResolvedParam | UnboundParameter | Unread | None:
    """Decides one param, dispatching on whether it is a filter."""
    if info.param_kind != "filter":
        return _resolve_nonfilter(info, resolution, ledger)
    filtered = _resolve_filter_param(info, infos, resolution.overrides)
    if isinstance(filtered, UnboundParameter):
        return filtered
    if info.name not in resolution.overrides:
        return ResolvedParam(value=filtered, provenance=Provenance.DEFAULTED)
    await read_filter(filtered)
    return ResolvedParam(value=filtered, provenance=Provenance.STATED)


async def resolve_params_with_intent(
    *,
    fetch_at: ParamFetcher,
    filter_reads: FilterReads,
    intent: ParamIntent,
    search_name: str,
    stated: Mapping[str, JsonValue],
) -> ResolvedParams:
    """Walks the dependency DAG and resolves each param from a stated value, an
    automatic value, the scalar default, or an open slot. Re-fetches after each pick
    so dependent params surface.

    Each stated value is read under the declarations fetched once its parents are
    bound. A name that is no parameter of the search raises ``UnknownParameterError``.
    """
    overrides: OverrideMap = {}
    context: dict[str, str] = {}
    params: dict[str, ParamValue] = {}
    open_slots: list[UnboundParameter] = []
    unresolved: list[str] = []
    unread: list[str] = []
    seen: set[str] = set()
    provenance: dict[str, Provenance] = {}
    ledger = _VocabLedger()
    for pass_index in range(_MAX_RESOLVE_DEPTH):
        declarations = await fetch_at(context)
        infos = format_param_info_typed(declarations)
        declared = {d.name: d for d in declarations}
        _refuse_hidden_overrides(infos, stated, search_name)
        overrides = _read_pass(
            infos, declarations, stated, context, overrides, first=pass_index == 0
        )
        # Siblings decide whether one numeric param owns a stated quantity.
        resolution = _Resolution(
            intent=intent, overrides=overrides, siblings=tuple(infos)
        )
        progressed = False
        # Overridden params resolve first so an authoritative value claims its
        # vocabulary slot before a sibling defaults onto it. Eviction covers dependent
        # params, which a later pass resolves after a default is already bound.
        resolved_this_pass: set[str] = set()
        for info in sorted(infos, key=lambda i: _resolution_rank(i, overrides)):
            _evict_for_override(
                info,
                overrides,
                ledger=ledger,
                params=params,
                context=context,
                seen=seen,
            )
            if (
                info.name in seen
                or _defer_to_next_pass(
                    info, context=context, resolved_this_pass=resolved_this_pass
                )
                or _awaits_comparator(info, infos, set(params) | set(unresolved))
            ):
                continue
            outcome = await _outcome_for(
                info,
                infos,
                resolution,
                ledger,
                partial(
                    refuse_filter_misses,
                    declared[info.name],
                    context={p: context[p] for p in info.wire_parents},
                    reads=filter_reads,
                ),
            )
            if isinstance(outcome, Unread):
                unread.append(outcome.param_name)
                unresolved.append(outcome.param_name)
            elif isinstance(outcome, UnboundParameter):
                slot = _visible_slot(info, outcome, search_name)
                if slot is not None:
                    open_slots.append(slot)
                    unresolved.append(info.name)
            elif outcome is not None:
                params[info.name] = outcome.value
                provenance[info.name] = outcome.provenance
                context[info.name] = to_wire(outcome.value)
                resolved_this_pass.add(info.name)
            seen.add(info.name)
            progressed = True
        if not progressed:
            break
    return ResolvedParams(
        params=params,
        provenance=provenance,
        open_slots=open_slots,
        unresolved_required=unresolved,
        unread=unread,
    )

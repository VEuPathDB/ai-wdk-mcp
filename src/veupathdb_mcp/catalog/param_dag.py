"""Deterministic resolution of a WDK search's parameter dependency DAG."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence

from pydantic import Field
from veupathdb.domain import SearchContext
from veupathdb.domain.parameters import (
    PHYLETIC_LIST_PARAMS,
    ParamValue,
    PhyleticBinding,
    UnboundParameter,
    to_wire,
)
from veupathdb.errors import ValidationError
from veupathdb.model import CamelModel
from veupathdb.wdk import WDKParameter, get_wdk_client

from veupathdb_mcp.catalog._param_binding import (
    OverrideMap,
    ResolvedParam,
    Unread,
    _apply_override,
    _Resolution,
    _resolve_nonfilter,
    _sole_claim,
    _VocabLedger,
)
from veupathdb_mcp.catalog._param_filters import _resolve_filter_param
from veupathdb_mcp.catalog.discovery_service import (
    get_discovery_service,
)
from veupathdb_mcp.catalog.hidden_params import HiddenParameterError
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
    infos: list[ParameterInfo], overrides: OverrideMap, *, first_pass: bool
) -> None:
    """Refuses an override that names no parameter of the search.

    The search names every parameter on the first fetch, so a name the walk would
    never read is a mistake, not a value to drop.
    """
    if not first_pass or not overrides:
        return
    names = {i.name for i in infos}
    unknown = sorted(set(overrides) - names)
    if unknown:
        raise UnknownParameterError(
            unknown, sorted(i.name for i in infos if i.is_visible)
        )


def _refuse_hidden_overrides(
    infos: list[ParameterInfo], overrides: OverrideMap
) -> None:
    for info in infos:
        if info.name in overrides and not info.is_visible:
            raise HiddenParameterError(info.name)


def _with_derived_phyletic(
    infos: list[ParameterInfo],
    overrides: OverrideMap,
    definition: Sequence[WDKParameter],
) -> OverrideMap:
    if not is_phyletic_sheet(infos):
        return overrides
    if not PHYLETIC_LIST_PARAMS & overrides.keys():
        raise PhyleticListError(PhyleticNoSelection())
    lists = {
        name: overrides[name] for name in PHYLETIC_LIST_PARAMS if name in overrides
    }
    match derive_phyletic_overrides(list(definition), lists):
        case PhyleticBinding() as binding:
            return {**overrides, **binding.model_dump()}
        case refused:
            raise PhyleticListError(refused)


def _visible_slot(
    info: ParameterInfo, slot: UnboundParameter
) -> UnboundParameter | None:
    if info.is_visible:
        return slot
    if info.param_kind != "input-step":
        raise HiddenParameterError(info.name, unset=True)
    return None


def _checked_overrides(
    infos: list[ParameterInfo],
    stated: OverrideMap,
    definition: Sequence[WDKParameter],
    *,
    first_pass: bool,
) -> OverrideMap | None:
    _refuse_unknown_overrides(infos, stated, first_pass=first_pass)
    _refuse_hidden_overrides(infos, stated)
    return _with_derived_phyletic(infos, stated, definition) if first_pass else None


ParamFetcher = Callable[[dict[str, str]], Awaitable[list[ParameterInfo]]]


def wdk_fetch_at(site_id: str, record_type: str, search_name: str) -> ParamFetcher:
    ctx = SearchContext(site_id, record_type, search_name)

    async def fetch_at(context: dict[str, str]) -> list[ParameterInfo]:
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
        params = resp.search_data.parameters or []
        return format_param_info_typed(params)

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
    wanted = _sole_claim(_apply_override(info, overrides[info.name]))
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
    depends_on = set(info.vocab_depends_on or [])
    if depends_on - context.keys():
        return True
    return bool(depends_on & resolved_this_pass)


def _outcome_for(
    info: ParameterInfo,
    infos: list[ParameterInfo],
    resolution: _Resolution,
    ledger: _VocabLedger,
) -> ResolvedParam | UnboundParameter | Unread | None:
    """Decides one param, dispatching on whether it is a filter."""
    if info.param_kind != "filter":
        return _resolve_nonfilter(info, resolution, ledger)
    filtered = _resolve_filter_param(info, infos, resolution.overrides)
    if isinstance(filtered, UnboundParameter):
        return filtered
    return ResolvedParam(
        value=filtered,
        provenance=(
            Provenance.STATED
            if info.name in resolution.overrides
            else Provenance.DEFAULTED
        ),
    )


async def resolve_params_with_intent(
    *,
    fetch_at: ParamFetcher,
    intent: ParamIntent,
    overrides: OverrideMap | None = None,
    definition: Sequence[WDKParameter] = (),
) -> ResolvedParams:
    """Walks the dependency DAG and resolves each param from an override, an automatic
    value, the scalar default, or an open slot. Re-fetches after each pick so dependent
    params surface.

    An override that names no parameter of the search raises ``UnknownParameterError``.
    """
    stated = overrides or {}
    overrides = stated
    context: dict[str, str] = {}
    params: dict[str, ParamValue] = {}
    open_slots: list[UnboundParameter] = []
    unresolved: list[str] = []
    unread: list[str] = []
    seen: set[str] = set()
    provenance: dict[str, Provenance] = {}
    ledger = _VocabLedger()
    resolution = _Resolution(intent=intent, overrides=overrides)
    for pass_index in range(_MAX_RESOLVE_DEPTH):
        infos = await fetch_at(context)
        overrides = (
            _checked_overrides(infos, stated, definition, first_pass=pass_index == 0)
            or overrides
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
            if info.name in seen or _defer_to_next_pass(
                info, context=context, resolved_this_pass=resolved_this_pass
            ):
                continue
            if _awaits_comparator(info, infos, set(params) | set(unresolved)):
                continue
            outcome = _outcome_for(info, infos, resolution, ledger)
            if isinstance(outcome, Unread):
                unread.append(outcome.param_name)
                unresolved.append(outcome.param_name)
            elif isinstance(outcome, UnboundParameter):
                slot = _visible_slot(info, outcome)
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

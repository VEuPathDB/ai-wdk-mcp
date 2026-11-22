"""Deterministic resolution of a WDK search's parameter dependency DAG."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterator, Mapping, Sequence
from functools import partial
from types import MappingProxyType
from typing import final

from pydantic import Field, JsonValue
from veupathdb.domain import SearchContext
from veupathdb.domain.parameters import (
    PHYLETIC_LIST_PARAMS,
    SHOWN_CANDIDATES,
    FilterClause,
    FilterFacet,
    FilterFacets,
    FilterProposals,
    FilterValue,
    MultiPickValue,
    NumberMembers,
    ParamGraph,
    ParamSpecNormalized,
    ParamValue,
    PhyleticBinding,
    SinglePickValue,
    Stated,
    StringMembers,
    UnboundParameter,
    VocabOption,
    entry_name,
    flatten_vocab,
    leaf_terms,
    rank_entries,
    read_stated_values,
    restates,
    shown_stated,
    shown_stated_text,
    to_wire,
    wire_map,
)
from veupathdb.errors import (
    ValidationError,
    VEuPathDBError,
    VEuPathDBErrorCode,
    param_message_rows,
)
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
from veupathdb_mcp.catalog._walk_refusals import Refusals, ancestors
from veupathdb_mcp.catalog.discovery_service import (
    get_discovery_service,
)
from veupathdb_mcp.catalog.facet_ranges import FilterReads, filter_miss
from veupathdb_mcp.catalog.param_adapters import adapt_param_from_wdk
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
    PhyleticNoSelection,
    derive_phyletic_overrides,
    is_phyletic_sheet,
    phyletic_refusal,
)
from veupathdb_mcp.catalog.search_context import (
    get_search_params_under_context,
)
from veupathdb_mcp.catalog.site_set_params import SiteSetParameterError
from veupathdb_mcp.catalog.vocab_resolve import (
    NamedVocabulary,
    ResolveContext,
    interleaved,
    ordered_terms,
    refused_names,
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
            errors=[
                {
                    "param": name,
                    "detail": f"{name} is no parameter of this search. Valid names: {valid}.",
                }
                for name in unknown
            ],
        )


def _note_unknown(
    infos: list[ParameterInfo], stated: Mapping[str, JsonValue], refused: Refusals
) -> None:
    """Notes each override that names no parameter of the search.

    The search names every parameter on the first fetch, so a name the walk would
    never read is a mistake, not a value to drop.
    """
    names = {i.name for i in infos}
    unknown = [name for name in stated if name not in names]
    if unknown:
        refused.note(
            UnknownParameterError(unknown, sorted(i.name for i in infos if i.bindable)),
            set(unknown),
        )


def _note_hidden(
    infos: list[ParameterInfo],
    stated: Mapping[str, JsonValue],
    search_name: str,
    refused: Refusals,
) -> None:
    for info in infos:
        if info.name in stated and info.site_set and info.name not in refused.names:
            refused.note(SiteSetParameterError(info.name, search_name), {info.name})


async def _derived_phyletic(
    infos: list[ParameterInfo],
    overrides: OverrideMap,
    declarations: Sequence[WDKParameter],
    refused: Refusals,
    about: ResolveContext | None,
    site_id: str,
) -> OverrideMap:
    if not is_phyletic_sheet(infos) or PHYLETIC_LIST_PARAMS & refused.names:
        return overrides
    lists = {
        name: to_wire(value)
        for name, value in overrides.items()
        if name in PHYLETIC_LIST_PARAMS
    }
    derived = (
        derive_phyletic_overrides(list(declarations), lists)
        if lists
        else PhyleticNoSelection()
    )
    match derived:
        case PhyleticBinding() as binding:
            return {**overrides, **read_declared(declarations, binding.model_dump())}
        case refused_lists:
            refusal = await phyletic_refusal(
                refused_lists, declarations, site_id, about
            )
    refused.note(refusal, refused_names(refusal))
    return overrides


def _visible_slot(
    info: ParameterInfo, slot: UnboundParameter, search_name: str, refused: Refusals
) -> UnboundParameter | None:
    if info.bindable:
        return slot
    if info.param_kind != "input-step":
        refused.note(
            SiteSetParameterError(info.name, search_name, unset=True), {info.name}
        )
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
            errors=[
                {
                    "param": name,
                    "detail": (
                        f"No read under the stated parents declares {name}, so its "
                        "value cannot be read."
                    ),
                }
                for name in unread
            ],
        )


def _bound(declaration: WDKParameter, read: Stated) -> ParamValue:
    """Binds a filter statement to its facets. A pick is already the entry the
    stated reader named."""
    match read:
        case FilterProposals():
            return FilterFacets.of(declaration).bind(read)
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


def _read_each(
    declarations: Sequence[WDKParameter],
    stated: Mapping[str, JsonValue],
    refused: Refusals,
) -> dict[str, ParamValue]:
    unread = [d for d in declarations if d.name in stated]
    while True:
        try:
            shapes = read_stated_values(unread, stated)
            break
        except ValidationError as refusal:
            named = refused_names(refusal) & {d.name for d in unread}
            if not named:
                raise
            refused.note(refusal, named, declarations)
            unread = [d for d in unread if d.name not in named]
    declared = {d.name: d for d in declarations}
    read: dict[str, ParamValue] = {}
    for name, shape in shapes.items():
        try:
            read[name] = _bound(declared[name], shape)
        except ValidationError as refusal:
            refused.note(refusal, {name}, declarations)
    return read


def _read_ready(
    declarations: Sequence[WDKParameter],
    stated: Mapping[str, JsonValue],
    context: dict[str, str],
    read: Mapping[str, ParamValue],
    refused: Refusals,
) -> dict[str, ParamValue]:
    """Reads each stated name not yet read or refused whose parents are in the
    context, under the declarations fetched at that context."""
    waiting = _waiting(declarations, stated, context) | refused.blocked(declarations)
    ready = [
        d
        for d in declarations
        if d.name in stated and d.name not in read and d.name not in waiting
    ]
    return _read_each(ready, stated, refused)


def _read_pass(
    declarations: Sequence[WDKParameter],
    stated: Mapping[str, JsonValue],
    context: dict[str, str],
    overrides: OverrideMap,
    refused: Refusals,
    *,
    first_pass: list[ParameterInfo] | None,
) -> OverrideMap:
    if first_pass is not None:
        _note_unknown(first_pass, stated, refused)
    return {
        **overrides,
        **_read_ready(declarations, stated, context, overrides, refused),
    }


async def _note_miss(
    refused: Refusals,
    declaration: WDKParameter,
    value: ParamValue,
    *,
    context: dict[str, str],
    reads: FilterReads,
) -> None:
    miss = await filter_miss(declaration, value, context, reads)
    if miss is not None:
        refused.note_miss(miss)


async def _note_misses(
    refused: Refusals,
    declarations: Sequence[WDKParameter],
    read: Mapping[str, ParamValue],
    context: dict[str, str],
    reads: FilterReads,
) -> None:
    parents = ParamGraph.of(declarations).wire_parents
    for declaration in declarations:
        if declaration.name in read:
            await _note_miss(
                refused,
                declaration,
                read[declaration.name],
                context={
                    p: context[p]
                    for p in parents.get(declaration.name, ())
                    if p in context
                },
                reads=reads,
            )


ParamFetcher = Callable[[dict[str, str]], Awaitable[list[WDKParameter]]]


NOTHING_BOUND: Mapping[str, ParamValue] = MappingProxyType({})


class _Reader:
    pass


_READER = _Reader()


@final
class BoundValues(Mapping[str, ParamValue]):
    __slots__ = ("_values",)

    def __init__(self, values: Mapping[str, ParamValue], reader: _Reader) -> None:
        if reader is not _READER:
            msg = "only read_under_parents binds values"
            raise TypeError(msg)
        self._values: Mapping[str, ParamValue] = MappingProxyType(dict(values))

    def __getitem__(self, name: str) -> ParamValue:
        return self._values[name]

    def __iter__(self) -> Iterator[str]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)


NOTHING_READ = BoundValues({}, _READER)


def as_tree_leaves(
    declarations: Sequence[WDKParameter], values: Mapping[str, ParamValue]
) -> dict[str, ParamValue]:
    """The stated values with each parent term of a countOnlyLeaves tree as its
    leaves, the form WDK counts. A term that names no node is left for the
    canonicalizer to refuse."""
    counted = {
        d.name: adapt_param_from_wdk(d) for d in declarations if d.count_only_leaves
    }
    return {name: _leaves(counted.get(name), value) for name, value in values.items()}


def _leaves(spec: ParamSpecNormalized | None, value: ParamValue) -> ParamValue:
    match value:
        case MultiPickValue(values=terms) if spec is not None:
            leaves = leaf_terms(spec.vocabulary, terms)
            return value if leaves is None else MultiPickValue(values=leaves)
        case _:
            return value


class MovedParentError(ValidationError):
    def __init__(
        self,
        child: str,
        held: ParamValue,
        moved: Mapping[str, tuple[ParamValue | None, ParamValue]],
        refusal: VEuPathDBError[VEuPathDBErrorCode],
        candidates: Sequence[str],
    ) -> None:
        self.child = child
        parents = ", ".join(
            f"{name} moved from {_shown(old)} to {shown_stated_text(new)}"
            for name, (old, new) in moved.items()
        )
        names = " and ".join(moved)
        refused = refusal.detail or refusal.title
        offered = (
            f" Under the new {names}, {child} offers: {'; '.join(candidates)}."
            if candidates
            else ""
        )
        detail = (
            f"{parents}, so {child}, which held {shown_stated_text(held)}, was read "
            f"again under it and refused: {refused}{offered} "
            f"State {child} again under the new {names}, or leave it out if a reader "
            "can keep it."
        )
        super().__init__(
            title="A held value no longer reads under its new parent",
            detail=detail,
            errors=param_message_rows({child: [detail]}),
        )


def _shown(value: ParamValue | None) -> str:
    return "unset" if value is None else shown_stated_text(value)


def _asked(
    declaration: WDKParameter, held: ParamValue
) -> list[tuple[NamedVocabulary, str, str]] | None:
    match held:
        case SinglePickValue(value=term):
            return _picked(declaration, [term])
        case MultiPickValue(values=terms):
            return _picked(declaration, terms)
        case FilterValue(filters=clauses) if clauses:
            facets = FilterFacets.of(declaration)
            return [
                (_facet_vocabulary(facet), _clause_phrase(clause), f"{facet.display}: ")
                for clause in clauses
                if (facet := facets.find(clause.field)) is not None and facet.members
            ]
        case _:
            return None


def _picked(
    declaration: WDKParameter, terms: Sequence[str]
) -> list[tuple[NamedVocabulary, str, str]]:
    vocabulary = NamedVocabulary(
        display=declaration.display_name or declaration.name,
        options=flatten_vocab(declaration.vocabulary),
    )
    return [(vocabulary, term, "") for term in terms]


def _facet_vocabulary(facet: FilterFacet) -> NamedVocabulary:
    return NamedVocabulary(
        display=facet.display,
        options=[VocabOption(value=member, display=member) for member in facet.members],
    )


def _clause_phrase(clause: FilterClause) -> str:
    match clause:
        case StringMembers(value=members):
            return " ".join(members)
        case NumberMembers(value=members):
            return " ".join(map(str, members))
        case _:
            return clause.field


async def _candidates(
    declaration: WDKParameter,
    held: ParamValue,
    about: ResolveContext | None,
    refused: str,
) -> list[str]:
    asked = _asked(declaration, held)
    if asked is None:
        named = [
            facet.display
            for facet in FilterFacets.of(declaration).root
            if facet.members
        ]
        return interleaved([named], str, SHOWN_CANDIDATES)
    pairs = [(vocabulary, phrase) for vocabulary, phrase, _ in asked]
    led = (
        await ordered_terms(about, pairs)
        if about is not None
        else [rank_entries(v.options, p, SHOWN_CANDIDATES) for v, p in pairs]
    )
    groups = [
        [
            f"{prefix}{entry_name(entry)}"
            for entry in entries
            if entry.value not in refused
        ]
        for (_, _, prefix), entries in zip(asked, led, strict=True)
    ]
    return interleaved(groups, str, SHOWN_CANDIDATES)


async def read_under_parents(
    fetch_at: ParamFetcher,
    stated: Mapping[str, JsonValue],
    reads: FilterReads,
    *,
    about: ResolveContext | None,
    bound: Mapping[str, ParamValue] = NOTHING_BOUND,
    stale: list[MovedParentError] | None = None,
) -> BoundValues:
    """Reads each stated value under the declarations its stated, bound and site-set
    parents give. Every problem of the call (a name of no parameter, a value that
    does not read, a filter that selects nothing) is one row of one refusal, in
    call order; a term no entry names carries its candidates ordered under
    ``about``, and None sends no choice."""
    read = await _read_held(
        fetch_at, stated, reads, about=about, bound=bound, noted=stale
    )
    return BoundValues(read, _READER)


async def _read_held(
    fetch_at: ParamFetcher,
    stated: Mapping[str, JsonValue],
    reads: FilterReads,
    *,
    about: ResolveContext | None,
    bound: Mapping[str, ParamValue],
    noted: list[MovedParentError] | None,
) -> dict[str, ParamValue]:
    first_context = wire_map({n: v for n, v in bound.items() if n not in stated})
    declarations = await fetch_at(first_context)
    fetched = _Fetched(fetch_at, first_context, declarations)
    graph = ParamGraph.of(declarations)
    given_back = {
        name: given
        for name, given in stated.items()
        if name in bound and restates(bound[name], given)
    }
    standing = {n: g for n, g in stated.items() if n not in given_back}
    refused = Refusals()
    read = await _read_standing(
        fetched,
        standing,
        reads,
        refused,
        bound={n: v for n, v in bound.items() if n not in standing},
    )
    moved = {
        name
        for name, value in read.items()
        if name not in bound or bound[name] != value
    }
    site_set = {d.name for d in declarations if d.site_set}
    followers = {
        name: given_back.get(name, shown_stated(value))
        for name, value in bound.items()
        if name not in standing
        and name not in site_set
        and ancestors(graph.wire_parents, name) & moved
    }
    read |= {n: bound[n] for n in given_back if n not in followers}
    unmoved = {n: v for n, v in bound.items() if n not in followers}
    order = graph.fill_order
    for child in sorted(
        followers, key=lambda name: order.index(name) if name in order else 0
    ):
        under = {**unmoved, **read}
        under_child = Refusals()
        try:
            got = await _read_standing(
                fetched, {child: followers[child]}, reads, under_child, bound=under
            )
        except VEuPathDBError as failure:
            if noted is None:
                raise
            refusal: VEuPathDBError[VEuPathDBErrorCode] = failure
            offered: list[str] = []
        else:
            read_refusal = await under_child.one([child], about)
            if read_refusal is None:
                read |= got
                continue
            refusal = read_refusal
            fresh = {d.name: d for d in await fetch_at(wire_map(under))}
            offered = (
                await _candidates(
                    fresh[child], bound[child], about, refusal.detail or refusal.title
                )
                if child in fresh
                else []
            )
        new_parents = {
            parent: (bound.get(parent), read[parent])
            for parent in sorted(ancestors(graph.wire_parents, child) & moved)
        }
        stale = MovedParentError(child, bound[child], new_parents, refusal, offered)
        if noted is None:
            refused.note(stale, {child})
        else:
            noted.append(stale)
    await refused.raise_once(list(stated), about)
    return read


class _Fetched:
    def __init__(
        self,
        fetch_at: ParamFetcher,
        context: dict[str, str],
        declarations: list[WDKParameter],
    ) -> None:
        self.fetch_at = fetch_at
        self._first: tuple[dict[str, str], list[WDKParameter]] | None = (
            context,
            declarations,
        )

    async def __call__(self, context: dict[str, str]) -> list[WDKParameter]:
        first, self._first = self._first, None
        if first is not None and first[0] == context:
            return first[1]
        return await self.fetch_at(context)


async def _read_standing(
    fetch_at: _Fetched,
    stated: Mapping[str, JsonValue],
    reads: FilterReads,
    refused: Refusals,
    *,
    bound: Mapping[str, ParamValue],
) -> dict[str, ParamValue]:
    if not stated:
        return {}
    context = wire_map({n: v for n, v in bound.items() if n not in stated})
    read: dict[str, ParamValue] = {}
    declarations = await fetch_at(context)
    _note_unknown(format_param_info_typed(declarations, organism=None), stated, refused)
    for _ in range(_MAX_RESOLVE_DEPTH):
        missing = stated.keys() - read.keys() - refused.blocked(declarations)
        if not missing:
            break
        waiting = _waiting(declarations, stated, context)
        sited = {
            d.name: d.initial_display_value
            for d in declarations
            if d.site_set
            and d.initial_display_value is not None
            and d.name not in context
            and d.name not in waiting
        }
        new = _read_ready(declarations, stated, context, read, refused)
        if not new and not sited:
            open_names = missing - refused.blocked(declarations)
            pending = [d for d in declarations if d.name in open_names]
            new = _read_each(pending, stated, refused)
        if not new and not sited:
            break
        await _note_misses(refused, declarations, new, context, reads)
        read |= new
        context |= sited | wire_map(new)
        if stated.keys() - read.keys():
            declarations = await fetch_at(context)
    unread = [
        name
        for name in stated
        if name not in read and name not in refused.blocked(declarations)
    ]
    if unread:
        refused.note(UnreadStatementError(unread), set(unread))
    return as_tree_leaves(declarations, read)


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
    search: SearchContext,
    stated: Mapping[str, JsonValue],
    about: ResolveContext | None,
) -> ResolvedParams:
    """Walks the dependency DAG and resolves each param from a stated value, an
    automatic value, the scalar default, or an open slot. Re-fetches after each pick
    so dependent params surface.

    Each stated value is read under the declarations fetched once its parents are
    bound. Every problem of the call is one row of one refusal raised at the end,
    in call order. A term no entry names carries its candidates ordered by
    ``ordered_refusal`` under ``about``; None leaves the ranking, for a caller
    that shows the refusal to no one.
    """
    overrides: OverrideMap = {}
    context: dict[str, str] = {}
    params: dict[str, ParamValue] = {}
    open_slots: list[UnboundParameter] = []
    unresolved: list[str] = []
    unread: list[str] = []
    seen: set[str] = set()
    provenance: dict[str, Provenance] = {}
    refused = Refusals()
    ledger = _VocabLedger()
    for pass_index in range(_MAX_RESOLVE_DEPTH):
        declarations = await fetch_at(context)
        infos = format_param_info_typed(declarations, organism=None)
        declared = {d.name: d for d in declarations}
        _note_hidden(infos, stated, search.search_name, refused)
        overrides = _read_pass(
            declarations,
            stated,
            context,
            overrides,
            refused,
            first_pass=infos if pass_index == 0 else None,
        )
        if pass_index == 0:
            overrides = await _derived_phyletic(
                infos, overrides, declarations, refused, about, search.site_id
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
        seen |= refused.names
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
                    _note_miss,
                    refused,
                    declared[info.name],
                    context={p: context[p] for p in info.wire_parents},
                    reads=filter_reads,
                ),
            )
            if isinstance(outcome, Unread):
                unread.append(outcome.param_name)
                unresolved.append(outcome.param_name)
            elif isinstance(outcome, UnboundParameter):
                slot = _visible_slot(info, outcome, search.search_name, refused)
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
    await refused.raise_once(list(stated), about)
    return ResolvedParams(
        params=params,
        provenance=provenance,
        open_slots=open_slots,
        unresolved_required=unresolved,
        unread=unread,
    )

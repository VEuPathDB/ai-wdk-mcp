"""The ranges and the selected count WDK reports for a stated filter value."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from veupathdb.domain.parameters import (
    DateBounds,
    DateRange,
    FacetRange,
    FilterClause,
    FilterFacet,
    FilterFacets,
    FilterValue,
    NumberBounds,
    NumberRange,
    ParamValue,
    VocabOption,
)
from veupathdb.errors import ValidationError
from veupathdb.wdk import WDKFilterParam, WDKParameter, get_wdk_client, in_turn_line

from veupathdb_mcp.catalog.discovery_service import get_discovery_service
from veupathdb_mcp.catalog.shortlist import matched

_RANGES_READ = 3


class FilterReads(Protocol):
    async def range(
        self,
        param: str,
        facet: FilterFacet,
        context: dict[str, str],
        others: Sequence[FilterClause],
    ) -> FacetRange | None: ...

    async def selected(
        self, param: str, context: dict[str, str], value: FilterValue
    ) -> int | None: ...


class EmptyRangeError(ValidationError):
    def __init__(
        self,
        param: str,
        facet: FilterFacet,
        span: FacetRange,
        stated: NumberBounds | DateBounds,
    ) -> None:
        detail = (
            f"{facet.term} ({facet.display}) on {param} spans {span.text()}; "
            f"{stated.text()} selects none of it. State a range inside it."
        )
        super().__init__(
            title="Range selects nothing",
            detail=detail,
            errors=[{"param": param, "field": facet.term, "detail": detail}],
        )


class TooFewSelectedError(ValidationError):
    def __init__(self, declaration: WDKFilterParam, count: int) -> None:
        unit = declaration.filter_data_type_display_name or "records"
        detail = (
            f"{declaration.name} ({declaration.display_name}) selects {count:,} "
            f"{unit}; it needs at least {declaration.min_selected_count:,}. "
            "State a wider filter."
        )
        super().__init__(
            title="Filter selects too few",
            detail=detail,
            errors=[{"param": declaration.name, "detail": detail}],
        )


async def filter_miss(
    declaration: WDKParameter,
    value: ParamValue,
    context: dict[str, str],
    reads: FilterReads,
) -> EmptyRangeError | TooFewSelectedError | None:
    match declaration, value:
        case WDKFilterParam(), FilterValue():
            empty = await _empty_range(declaration, value, context, reads)
            if empty is not None or declaration.min_selected_count <= 0:
                return empty
            count = await reads.selected(declaration.name, context, value)
            if count is not None and count < declaration.min_selected_count:
                return TooFewSelectedError(declaration, count)
    return None


async def _empty_range(
    declaration: WDKFilterParam,
    value: FilterValue,
    context: dict[str, str],
    reads: FilterReads,
) -> EmptyRangeError | None:
    facets = {facet.term: facet for facet in FilterFacets.of(declaration).root}
    for clause in value.filters:
        match clause:
            case NumberRange(value=bounds) | DateRange(value=bounds):
                facet = facets[clause.field]
                others = [c for c in value.filters if c is not clause]
                span = await reads.range(declaration.name, facet, context, others)
                if span is not None and not span.selects(bounds):
                    return EmptyRangeError(declaration.name, facet, span, bounds)
    return None


async def with_ranges(
    param: str,
    facets: list[FilterFacet],
    query: str,
    context: dict[str, str],
    reads: FilterReads,
) -> list[FilterFacet]:
    ranged = {facet.term: facet for facet in facets if facet.ranged}
    named = matched(
        [VocabOption(value=f.term, display=f.display) for f in ranged.values()], query
    )
    read = [ranged[option.value] for option in named[:_RANGES_READ]]
    return [
        *[
            facet.model_copy(
                update={"range": await reads.range(param, facet, context, [])}
            )
            for facet in read
        ],
        *[facet for facet in facets if facet not in read],
    ]


@dataclass(frozen=True)
class WDKFilterReads:
    site_id: str
    record_type: str
    search_name: str

    async def range(
        self,
        param: str,
        facet: FilterFacet,
        context: dict[str, str],
        others: Sequence[FilterClause],
    ) -> FacetRange | None:
        held = (await get_discovery_service().get_catalog(self.site_id)).facet_ranges
        key = (
            self.record_type,
            self.search_name,
            param,
            facet.term,
            tuple(sorted(context.items())),
            frozenset(clause.key for clause in others),
        )
        if key not in held:
            async with in_turn_line(self.site_id):
                summary = await get_wdk_client(self.site_id).get_ontology_term_summary(
                    self.record_type,
                    self.search_name,
                    param,
                    facet.term,
                    {**context, param: FilterValue().to_wire()},
                    filters=others,
                )
            held[key] = FacetRange.of(summary, facet)
        return held[key]

    async def selected(
        self, param: str, context: dict[str, str], value: FilterValue
    ) -> int | None:
        async with in_turn_line(self.site_id):
            counts = await get_wdk_client(self.site_id).get_filter_summary_counts(
                self.record_type,
                self.search_name,
                param,
                {**context, param: FilterValue().to_wire()},
                filters=value.filters,
            )
        return counts.native_filtered

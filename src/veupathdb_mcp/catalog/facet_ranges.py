"""The ranges and the selected count WDK reports for a stated filter value."""

from __future__ import annotations

import json
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
from veupathdb.model import CamelModel
from veupathdb.wdk import WDKFilterParam, WDKParameter, get_wdk_client
from veupathdb.wdk.search_load import in_turn_line

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
        bounds = json.dumps(stated.model_dump(mode="json", exclude_none=True))
        super().__init__(
            title="Range selects nothing",
            detail=(
                f"{facet.term} ({facet.display}) on {param} spans {span.text()}; "
                f"{bounds} selects none of it. State a range inside it."
            ),
            errors=[{"param": param, "field": facet.term}],
        )


class TooFewSelectedError(ValidationError):
    def __init__(self, declaration: WDKFilterParam, count: int) -> None:
        unit = declaration.filter_data_type_display_name or "records"
        super().__init__(
            title="Filter selects too few",
            detail=(
                f"{declaration.name} ({declaration.display_name}) selects {count:,} "
                f"{unit}; it needs at least {declaration.min_selected_count:,}. "
                "State a wider filter."
            ),
            errors=[{"param": declaration.name}],
        )


async def refuse_filter_misses(
    declaration: WDKParameter,
    value: ParamValue,
    context: dict[str, str],
    reads: FilterReads,
) -> None:
    match declaration, value:
        case WDKFilterParam(), FilterValue():
            await _refuse_empty_ranges(declaration, value, context, reads)
            if declaration.min_selected_count > 0:
                count = await reads.selected(declaration.name, context, value)
                if count is not None and count < declaration.min_selected_count:
                    raise TooFewSelectedError(declaration, count)


async def _refuse_empty_ranges(
    declaration: WDKFilterParam,
    value: FilterValue,
    context: dict[str, str],
    reads: FilterReads,
) -> None:
    facets = {facet.term: facet for facet in FilterFacets.of(declaration).root}
    for clause in value.filters:
        match clause:
            case NumberRange(value=bounds) | DateRange(value=bounds):
                facet = facets[clause.field]
                others = [c for c in value.filters if c is not clause]
                span = await reads.range(declaration.name, facet, context, others)
                if span is not None and not span.selects(bounds):
                    raise EmptyRangeError(declaration.name, facet, span, bounds)


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


class _SummaryCounts(CamelModel):
    native_filtered: int | None = None


@dataclass(frozen=True)
class _WDKFilterReads:
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
            raw = await get_wdk_client(self.site_id).post(
                f"/record-types/{self.record_type}/searches/{self.search_name}"
                f"/{param}/summary-counts",
                json={
                    "filters": value.model_dump(by_alias=True, mode="json")["filters"],
                    "contextParamValues": {
                        **context,
                        param: FilterValue().to_wire(),
                    },
                },
            )
        return _SummaryCounts.model_validate(raw).native_filtered


def wdk_filter_reads(site_id: str, record_type: str, search_name: str) -> FilterReads:
    return _WDKFilterReads(site_id, record_type, search_name)

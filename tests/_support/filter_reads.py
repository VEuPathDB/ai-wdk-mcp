"""A stand-in for the filter reads a walk makes of WDK."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from veupathdb.domain.parameters import (
    FacetRange,
    FilterClause,
    FilterFacet,
    FilterValue,
)
from veupathdb.testing.wdk_fixtures import load_recorded
from veupathdb.wdk import WDKOntologyTermSummary


@dataclass
class FilterReadsDouble:
    """Answers each range from the recorded term summary its facet names, alone or
    under sibling clauses, and the selected count it holds; records every read."""

    summaries: dict[str, str] = field(default_factory=dict)
    count: int | None = None
    under_siblings: dict[str, str] = field(default_factory=dict)
    ranges_read: list[tuple[str, str, dict[str, str], tuple[FilterClause, ...]]] = (
        field(default_factory=list)
    )
    counts_read: list[tuple[str, dict[str, str], FilterValue]] = field(
        default_factory=list
    )

    async def range(
        self,
        param: str,
        facet: FilterFacet,
        context: dict[str, str],
        others: Sequence[FilterClause],
    ) -> FacetRange | None:
        self.ranges_read.append((param, facet.term, context, tuple(others)))
        held = self.under_siblings if others else self.summaries
        name = held.get(facet.term)
        if name is None:
            return None
        summary = WDKOntologyTermSummary.model_validate(load_recorded(name).json_body())
        return FacetRange.of(summary, facet)

    async def selected(
        self, param: str, context: dict[str, str], value: FilterValue
    ) -> int | None:
        self.counts_read.append((param, context, value))
        return self.count

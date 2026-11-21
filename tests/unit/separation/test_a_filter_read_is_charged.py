"""A filter read a binding makes is charged to the run's WDK budget."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import JsonValue
from tests._support.filter_reads import FilterReadsDouble
from veupathdb.devtools import WDKExchange
from veupathdb.domain.parameters import FilterValue
from veupathdb.testing import NEEDS_QA_RECORDING, needs_qa_recording
from veupathdb.wdk import WDKParameter, WDKSearchResponse

from veupathdb_mcp.separation.budget import SEARCH_READ_REQUESTS, WdkCallBudget
from veupathdb_mcp.separation.enumerate import (
    CandidateSource,
    Proposal,
    _charged,
    _ChargedReads,
    bind,
)

_REFRESH = (
    Path(__file__).parents[1]
    / "catalog"
    / "fixtures"
    / "plasmodb_variant_characteristics_refresh.json"
)
_SEARCH = "GenesByVariantCharacteristics"

pytestmark = pytest.mark.skipif(
    needs_qa_recording("wdk/search_genes_by_variant_characteristics.json"),
    reason=NEEDS_QA_RECORDING,
)


async def _spent(clause: JsonValue) -> tuple[int, FilterReadsDouble]:
    response = WDKSearchResponse.model_validate(
        WDKExchange.model_validate_json(_REFRESH.read_text()).response_json
    )
    search = response.search_data

    async def fetch_at(context: dict[str, str]) -> list[WDKParameter]:
        del context
        return search.parameters or []

    budget = WdkCallBudget(limit=100)
    reads = FilterReadsDouble()
    await bind(
        search,
        _charged(fetch_at, budget, _SEARCH, set()),
        _ChargedReads(reads, budget),
        Proposal(
            search_name=_SEARCH,
            source=CandidateSource.CATALOG,
            basis="the site's catalog",
            stated={"gene_variant_stats": [clause]},
        ),
        ["Plasmodium falciparum 3D7"],
    )
    return budget.spent, reads


async def test_a_range_read_is_charged_once_beside_the_search_reads() -> None:
    members, _ = await _spent({"field": "most_severe_impact", "value": ["HIGH"]})
    ranged, reads = await _spent({"field": "total_variants", "value": {"min": 6}})

    assert len(reads.ranges_read) == 1
    assert ranged - members == SEARCH_READ_REQUESTS


async def test_a_count_read_is_charged() -> None:
    budget = WdkCallBudget(limit=100)
    reads = FilterReadsDouble(count=3)

    await _ChargedReads(reads, budget).selected("p", {}, FilterValue())

    assert budget.spent == SEARCH_READ_REQUESTS

"""The internal strategy an enrichment run holds its step in is named by the caller."""

from __future__ import annotations

from tests._support.enrichment_wdk import GO_ROW, FakeStrategyAPI, wdk

from veupathdb_mcp.wdk.enrichment.service import (
    DEFAULT_ENRICHMENT_STRATEGY_NAME,
    EnrichmentService,
)

__all__ = ["wdk"]


async def test_the_default_name_names_no_product(wdk: FakeStrategyAPI) -> None:
    wdk.rows["go-enrichment"] = [GO_ROW]

    await EnrichmentService().run_batch(
        site_id="plasmodb",
        analysis_types=["go_function"],
        search_name="GeneByLocusTag",
        parameters={},
    )

    assert wdk.strategy_names == [DEFAULT_ENRICHMENT_STRATEGY_NAME]
    assert "pathfinder" not in DEFAULT_ENRICHMENT_STRATEGY_NAME.lower()


async def test_the_caller_names_the_strategy(wdk: FakeStrategyAPI) -> None:
    wdk.rows["go-enrichment"] = [GO_ROW]

    await EnrichmentService(strategy_name="Pathfinder enrichment analysis").run_batch(
        site_id="plasmodb",
        analysis_types=["go_function"],
        search_name="GeneByLocusTag",
        parameters={},
    )

    assert wdk.strategy_names == ["Pathfinder enrichment analysis"]

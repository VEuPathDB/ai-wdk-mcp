"""A sample of a genome-sized transcript step answers in seconds, one row per gene."""

from __future__ import annotations

import time

import pytest
from veupathdb.domain.parameters import MultiPickValue
from veupathdb.domain.strategy import CombineOp
from veupathdb.wdk import (
    CombinedStepSpec,
    NewStepSpec,
    StrategyAPI,
    WDKSearchConfig,
    WDKStepTree,
    encode_params,
    get_strategy_api,
    is_internal_wdk_strategy_name,
    strip_internal_wdk_strategy_name,
)

from veupathdb_mcp.controls import delete_temp_strategy
from veupathdb_mcp.tool_payloads import gene_sample_attributes
from veupathdb_mcp.wdk import step_sample_records

pytestmark = pytest.mark.live_wdk

SITE = "plasmodb"
STRATEGY_NAME = "live lane genome union sample"
GENOME = {"organism": MultiPickValue(values=["Plasmodium falciparum 3D7"])}
SAMPLE_SIZE = 8
SAMPLE_SECONDS = 5.0


async def _genome_step(api: StrategyAPI, name: str) -> int:
    step = await api.create_step(
        NewStepSpec(
            search_name="GenesByTaxon",
            search_config=WDKSearchConfig(parameters=encode_params(GENOME)),
            custom_name=name,
        ),
        record_type="transcript",
    )
    return step.id


async def _leftovers(api: StrategyAPI) -> list[int]:
    return [
        summary.strategy_id
        for summary in await api.list_strategies()
        if is_internal_wdk_strategy_name(summary.name)
        and strip_internal_wdk_strategy_name(summary.name) == STRATEGY_NAME
    ]


async def test_a_genome_union_samples_distinct_genes_in_seconds(
    wdk_identity: str,
) -> None:
    del wdk_identity
    api = get_strategy_api(SITE)
    left = await _genome_step(api, "genome left")
    right = await _genome_step(api, "genome right")
    union = await api.create_combined_step(
        CombinedStepSpec(
            primary_step_id=left,
            secondary_step_id=right,
            boolean_operator=CombineOp.UNION,
        ),
        record_type="transcript",
    )
    created = await api.create_strategy(
        step_tree=WDKStepTree(
            step_id=union.id,
            primary_input=WDKStepTree(step_id=left),
            secondary_input=WDKStepTree(step_id=right),
        ),
        name=STRATEGY_NAME,
        is_internal=True,
    )
    try:
        genes = await api.get_step_count(union.id)
        started = time.perf_counter()
        sample = await step_sample_records(
            SITE,
            union.id,
            limit=SAMPLE_SIZE,
            attributes=gene_sample_attributes("transcript"),
        )
        seconds = time.perf_counter() - started
    finally:
        await delete_temp_strategy(api, created.id)

    ids = [row["id"] for row in sample.records]
    assert seconds < SAMPLE_SECONDS
    assert sample.total_count == genes
    assert len(ids) == SAMPLE_SIZE
    assert len(set(ids)) == SAMPLE_SIZE
    assert all(row["organism"] == "Plasmodium falciparum 3D7" for row in sample.records)
    assert await _leftovers(api) == []

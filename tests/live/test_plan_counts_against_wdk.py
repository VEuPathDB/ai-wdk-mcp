"""Counting an unbuilt plan against a running site, and leaving nothing behind."""

from __future__ import annotations

import pytest
from veupathdb.domain.parameters import StringValue
from veupathdb.domain.strategy import CombineOp, StrategyAst, StrategyStepNode
from veupathdb.wdk import get_strategy_api, is_internal_wdk_strategy_name

from veupathdb_mcp.wdk.plan_counts import compute_plan_step_counts

pytestmark = pytest.mark.live_wdk

SITE = "plasmodb"
STRATEGY_NAME = "live lane step counts"
ORGANISM = "Plasmodium falciparum 3D7"


def _weight_step(step_id: str, low: str, high: str) -> StrategyStepNode:
    return StrategyStepNode(
        id=step_id,
        search_name="GenesByMolecularWeight",
        parameters={
            "organism": StringValue(value=f'["{ORGANISM}"]'),
            "min_molecular_weight": StringValue(value=low),
            "max_molecular_weight": StringValue(value=high),
        },
    )


async def test_a_leaf_only_plan_counts_without_creating_anything(
    wdk_identity: str,
) -> None:
    del wdk_identity
    plan = StrategyAst(
        record_type="transcript", root=_weight_step("light", "10000", "20000")
    )

    counts = await compute_plan_step_counts(plan, SITE, strategy_name=STRATEGY_NAME)

    assert counts["light"] is not None
    assert 0 < counts["light"] < 100_000


async def test_a_combine_plan_counts_and_deletes_its_strategy(
    wdk_identity: str,
) -> None:
    del wdk_identity
    plan = StrategyAst(
        record_type="transcript",
        root=StrategyStepNode(
            id="both",
            search_name="__combine__",
            operator=CombineOp.INTERSECT,
            primary_input=_weight_step("light", "10000", "30000"),
            secondary_input=_weight_step("heavy", "20000", "40000"),
        ),
    )

    counts = await compute_plan_step_counts(plan, SITE, strategy_name=STRATEGY_NAME)

    assert set(counts) == {"light", "heavy", "both"}
    assert all(count is not None for count in counts.values())
    assert counts["both"] is not None
    assert counts["light"] is not None
    assert counts["both"] <= counts["light"]

    remaining = await get_strategy_api(SITE).list_strategies()
    assert not [
        item
        for item in remaining
        if is_internal_wdk_strategy_name(item.name) and STRATEGY_NAME in item.name
    ]

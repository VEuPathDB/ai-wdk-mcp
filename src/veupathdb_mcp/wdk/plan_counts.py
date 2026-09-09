"""Result counts for a strategy plan WDK has not built yet.

A leaf-only plan is counted with parallel anonymous reports. Any other plan
needs a temporary internal WDK strategy, which is deleted once read.
"""

import asyncio

from veupathdb.domain.parameters.values import ParamValue
from veupathdb.domain.strategy.ast import StrategyStepNode
from veupathdb.domain.strategy.ops import DEFAULT_COMBINE_OPERATOR, CombineOp
from veupathdb.domain.strategy.strategy_ast import StrategyAst
from veupathdb.domain.strategy.tree import leaves, walk
from veupathdb.errors import VEuPathDBError
from veupathdb.json_types import JSONObject
from veupathdb.logging import get_logger
from veupathdb.wdk.client import VEuPathDBClient
from veupathdb.wdk.factory import get_strategy_api
from veupathdb.wdk.strategy_api import StrategyAPI
from veupathdb.wdk.value_decoding import encode_params
from veupathdb.wdk.wdk_models import (
    CombinedStepSpec,
    NewStepSpec,
    WDKSearchConfig,
)

from veupathdb_mcp.controls.control_helpers import delete_temp_strategy
from veupathdb_mcp.wdk.step_tree import MissingWDKStepIdError, build_wdk_step_tree

__all__ = [
    "DEFAULT_PLAN_COUNTS_STRATEGY_NAME",
    "compute_plan_step_counts",
    "is_leaf_only_plan",
]

logger = get_logger(__name__)

DEFAULT_PLAN_COUNTS_STRATEGY_NAME = "step counts"


def is_leaf_only_plan(root: StrategyStepNode) -> bool:
    """Whether every step in the plan tree is a search step."""
    return len(leaves(root)) == len(walk(root))


async def compute_plan_step_counts(
    payload: StrategyAst,
    site_id: str,
    *,
    strategy_name: str = DEFAULT_PLAN_COUNTS_STRATEGY_NAME,
) -> dict[str, int | None]:
    """Per-step result counts for a plan, keyed by the plan's own step ids.

    ``strategy_name`` names the temporary strategy a non-leaf-only plan needs.
    A step whose count cannot be read is reported as ``None``.
    """
    api = get_strategy_api(site_id)
    if is_leaf_only_plan(payload.root):
        return await _compute_leaf_counts_parallel(
            api.client, payload.root, payload.record_type
        )
    return await _compute_counts_via_temp_strategy(
        api, payload, site_id, strategy_name=strategy_name
    )


async def _count_via_anonymous_report(
    client: VEuPathDBClient,
    record_type: str,
    search_name: str,
    parameters: dict[str, ParamValue],
) -> int | None:
    """The result count of one search, from the anonymous report endpoint.

    A report with ``numRecords: 0`` returns only ``meta.totalCount``, so no
    step and no strategy is created. Returns ``None`` on failure.
    """
    config = WDKSearchConfig(parameters=encode_params(parameters))
    report_config: JSONObject = {"pagination": {"offset": 0, "numRecords": 0}}
    try:
        answer = await client.run_search_report(
            record_type, search_name, config, report_config
        )
    except VEuPathDBError as e:
        logger.warning(
            "Anonymous report count failed",
            record_type=record_type,
            search_name=search_name,
            error=str(e),
        )
        return None
    else:
        return answer.meta.records_returned()


async def _compute_leaf_counts_parallel(
    client: VEuPathDBClient,
    root: StrategyStepNode,
    record_type: str,
) -> dict[str, int | None]:
    """Count every leaf step at once with anonymous reports."""
    all_steps = walk(root)
    tasks = [
        _count_via_anonymous_report(
            client,
            record_type,
            step.search_name,
            step.parameters,
        )
        for step in all_steps
    ]
    results = await asyncio.gather(*tasks)
    return {step.id: count for step, count in zip(all_steps, results, strict=True)}


async def _create_combine_wdk_step(
    api: StrategyAPI,
    step: StrategyStepNode,
    record_type: str,
    primary_wdk_id: int,
    secondary_wdk_id: int,
) -> int | None:
    """Create a WDK combine or colocation step."""
    if step.operator == CombineOp.COLOCATE:
        coloc = step.colocation_params
        if coloc is None:
            return None
        # The GenesBySpanLogic AnswerParams are blank at creation and WDK wires
        # them from the step tree later.
        result = await api.create_transform_step(
            NewStepSpec(
                search_name="GenesBySpanLogic",
                search_config=WDKSearchConfig(parameters=coloc.to_wdk_params()),
            ),
            input_step_id=primary_wdk_id,
            record_type="transcript",
        )
        return result.id
    result = await api.create_combined_step(
        CombinedStepSpec(
            primary_step_id=primary_wdk_id,
            secondary_step_id=secondary_wdk_id,
            boolean_operator=step.operator or DEFAULT_COMBINE_OPERATOR,
        ),
        record_type=record_type,
    )
    return result.id


async def _create_wdk_step(
    api: StrategyAPI,
    step: StrategyStepNode,
    record_type: str,
    wdk_step_ids: dict[str, int],
) -> int | None:
    """Create one WDK step and return its WDK id, or None on failure."""
    kind = step.infer_kind()
    params = encode_params(step.parameters)
    try:
        if kind == "search":
            result = await api.create_step(
                NewStepSpec(
                    search_name=step.search_name,
                    search_config=WDKSearchConfig(parameters=params),
                ),
                record_type=record_type,
            )
            return result.id
        if kind == "transform" and step.primary_input_id:
            input_wdk_id = wdk_step_ids.get(step.primary_input_id)
            if input_wdk_id is None:
                return None
            result = await api.create_transform_step(
                NewStepSpec(
                    search_name=step.search_name,
                    search_config=WDKSearchConfig(parameters=params),
                ),
                input_step_id=input_wdk_id,
                record_type=record_type,
            )
            return result.id
        if kind == "combine" and step.primary_input_id and step.secondary_input_id:
            primary_wdk_id = wdk_step_ids.get(step.primary_input_id)
            secondary_wdk_id = wdk_step_ids.get(step.secondary_input_id)
            if primary_wdk_id is None or secondary_wdk_id is None:
                return None
            return await _create_combine_wdk_step(
                api,
                step,
                record_type,
                primary_wdk_id,
                secondary_wdk_id,
            )
    except VEuPathDBError as exc:
        logger.warning(
            "Failed to create step for count computation",
            step_id=step.id,
            error=str(exc),
        )
    return None


async def _read_counts_from_strategy(
    api: StrategyAPI,
    strategy_id: int,
    all_steps: list[StrategyStepNode],
    wdk_step_ids: dict[str, int],
    counts: dict[str, int | None],
) -> None:
    """Read estimatedSize from a WDK strategy into ``counts``."""
    try:
        wdk_strategy = await api.get_strategy(strategy_id)
        for step in all_steps:
            wdk_id = wdk_step_ids.get(step.id)
            if wdk_id is None:
                continue
            wdk_step = wdk_strategy.steps.get(str(wdk_id))
            if wdk_step is not None and wdk_step.estimated_size is not None:
                counts[step.id] = wdk_step.estimated_size
    except VEuPathDBError as e:
        logger.warning("Failed to read counts from strategy payload", error=str(e))


async def _compute_counts_via_temp_strategy(
    api: StrategyAPI,
    payload: StrategyAst,
    site_id: str,
    *,
    strategy_name: str,
) -> dict[str, int | None]:
    """Count a plan through a temporary strategy, deleted once its counts are read."""
    all_steps = walk(payload.root)

    wdk_step_ids: dict[str, int] = {}
    for step in all_steps:
        wdk_id = await _create_wdk_step(api, step, payload.record_type, wdk_step_ids)
        if wdk_id is not None:
            wdk_step_ids[step.id] = wdk_id

    counts: dict[str, int | None] = {step.id: None for step in all_steps}

    # Every step must exist on WDK before the tree can be built.
    if len(wdk_step_ids) != len(all_steps):
        return counts

    try:
        step_tree = build_wdk_step_tree(payload.root, wdk_step_ids)
    except MissingWDKStepIdError:
        return counts

    temp_strategy_id: int | None = None
    try:
        created = await api.create_strategy(
            step_tree=step_tree,
            name=strategy_name,
            description=None,
            is_internal=True,
        )
        temp_strategy_id = created.id
    except VEuPathDBError as exc:
        logger.exception(
            "Failed to create temporary WDK strategy for step counts",
            error=str(exc),
            site_id=site_id,
            step_count=len(all_steps),
        )

    if temp_strategy_id is not None:
        await _read_counts_from_strategy(
            api, temp_strategy_id, all_steps, wdk_step_ids, counts
        )

    await delete_temp_strategy(api, temp_strategy_id)
    return counts

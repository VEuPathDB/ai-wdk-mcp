"""Positive/negative control test helpers for planning mode.

These helpers run *temporary* WDK steps/strategies to evaluate whether known
positive controls are returned and known negative controls are excluded.
"""

from pydantic import JsonValue
from veupathdb.domain.parameters.values import ParamValue, StringValue
from veupathdb.domain.search import SearchContext
from veupathdb.errors import VEuPathDBError
from veupathdb.json_types import JSONObject
from veupathdb.logging import get_logger
from veupathdb.wdk.factory import (
    get_results_api,
    get_strategy_api,
)
from veupathdb.wdk.strategy_api import StrategyAPI
from veupathdb.wdk.value_decoding import encode_params
from veupathdb.wdk.wdk_models import (
    CombinedStepSpec,
    NewStepSpec,
    WDKDatasetConfigIdList,
    WDKDatasetIdListContent,
    WDKSearchConfig,
    WDKStepTree,
)
from veupathdb.wdk.wdk_parameters import WDKParameter

from veupathdb_mcp.catalog.searches import find_record_type_for_search
from veupathdb_mcp.controls.control_helpers import (
    _encode_id_list,
    _get_total_count_for_step,
    cleanup_internal_control_test_strategies,
    delete_temp_strategy,
)
from veupathdb_mcp.controls.control_types import (
    ControlSetData,
    ControlTargetData,
    ControlTestResult,
    IntersectionConfig,
    summarize_intersection,
)
from veupathdb_mcp.wdk.helpers import extract_record_ids

__all__ = [
    "resolve_controls_param_type",
    "run_positive_negative_controls",
    "run_step_control_tests",
]

logger = get_logger(__name__)

_MAX_REPORTED_IDS = 20


async def run_step_control_tests(
    site_id: str,
    wdk_step_id: int,
    positive_controls: list[str] | None = None,
    negative_controls: list[str] | None = None,
) -> ControlTestResult:
    """Intersect an already-built step's results with the control gene lists."""
    answer = await get_results_api(site_id).get_step_preview(wdk_step_id, limit=50000)
    result_ids = {record.display_name for record in answer.records}

    target = ControlTargetData(
        step_id=wdk_step_id,
        estimated_size=answer.meta.records_returned(),
    )
    result = ControlTestResult(site_id=site_id, target=target)

    if positive_controls:
        positives = set(positive_controls)
        recovered = result_ids & positives
        result.positive = ControlSetData(
            controls_count=len(positives),
            intersection_count=len(recovered),
            intersection_ids_sample=sorted(recovered)[:_MAX_REPORTED_IDS],
            missing_ids_sample=sorted(positives - result_ids)[:_MAX_REPORTED_IDS],
            recall=len(recovered) / len(positives),
        )

    if negative_controls:
        negatives = set(negative_controls)
        hits = result_ids & negatives
        result.negative = ControlSetData(
            controls_count=len(negatives),
            intersection_count=len(hits),
            intersection_ids_sample=sorted(hits)[:_MAX_REPORTED_IDS],
            false_positive_rate=len(hits) / len(negatives),
        )

    return result


def _find_param_type(params: list[WDKParameter], param_name: str) -> str | None:
    for p in params:
        if p.name == param_name:
            return p.type
    return None


async def resolve_controls_param_type(
    api: StrategyAPI,
    record_type: str,
    controls_search_name: str,
    controls_param_name: str,
) -> str | None:
    """Return the WDK param type for a controls parameter."""
    try:
        response = await api.client.get_search_details(
            record_type, controls_search_name
        )
        params = response.search_data.parameters
        if params is not None:
            return _find_param_type(params, controls_param_name)
    except VEuPathDBError as exc:
        logger.warning(
            "Could not resolve param type for controls",
            search=controls_search_name,
            param=controls_param_name,
            record_type=record_type,
            error=str(exc),
        )
    return None


async def _run_intersection_control(
    config: IntersectionConfig,
    controls_ids: list[str],
    fetch_ids_limit: int = 500,
) -> JSONObject:
    """Run a single control intersection and return results.

    Each call creates its own target step, because WDK deletes every step of
    a strategy together with the strategy.
    """
    api = get_strategy_api(config.site_id)

    # A search has one correct record type, which the catalog knows. A gene
    # search lives under "transcript".
    target_rt = await find_record_type_for_search(
        SearchContext(config.site_id, config.record_type, config.target_search_name)
    )
    controls_rt = await find_record_type_for_search(
        SearchContext(config.site_id, config.record_type, config.controls_search_name)
    )

    target_step = await api.create_step(
        NewStepSpec(
            search_name=config.target_search_name,
            search_config=WDKSearchConfig(
                parameters=encode_params(config.target_parameters),
            ),
            custom_name="Target",
        ),
        record_type=target_rt,
    )
    target_step_id = target_step.id

    # Determine whether the controls parameter is an input-dataset type.
    # If so, upload the IDs as a WDK dataset and pass the dataset ID.
    param_type = await resolve_controls_param_type(
        api, controls_rt, config.controls_search_name, config.controls_param_name
    )

    controls_params: dict[str, ParamValue] = dict(
        config.controls_extra_parameters or {}
    )
    if param_type == "input-dataset":
        config_ds = WDKDatasetConfigIdList(
            source_type="idList",
            source_content=WDKDatasetIdListContent(ids=controls_ids),
        )
        dataset_id = await api.create_dataset(config_ds)
        controls_params[config.controls_param_name] = StringValue(value=str(dataset_id))
    else:
        controls_params[config.controls_param_name] = StringValue(
            value=_encode_id_list(controls_ids, config.controls_value_format),
        )

    controls_step = await api.create_step(
        NewStepSpec(
            search_name=config.controls_search_name,
            search_config=WDKSearchConfig(parameters=encode_params(controls_params)),
            custom_name="Controls",
        ),
        record_type=controls_rt,
    )
    controls_step_id = controls_step.id

    combined_step = await api.create_combined_step(
        CombinedStepSpec(
            primary_step_id=target_step_id,
            secondary_step_id=controls_step_id,
            boolean_operator=config.boolean_operator,
            custom_name=f"{config.boolean_operator} controls",
        ),
        record_type=target_rt,
    )
    combined_step_id = combined_step.id

    # WDK requires steps to be part of a strategy before they can be
    # queried for results (StepService enforces this).
    root = WDKStepTree(
        step_id=combined_step_id,
        primary_input=WDKStepTree(step_id=target_step_id),
        secondary_input=WDKStepTree(step_id=controls_step_id),
    )
    temp_strategy_id: int | None = None
    try:
        created = await api.create_strategy(
            step_tree=root,
            name=config.internal_strategy_name,
            description=None,
            is_internal=True,
        )
        temp_strategy_id = created.id

        target_total = await _get_total_count_for_step(api, target_step_id)
        total = await _get_total_count_for_step(api, combined_step_id)
        ids_found: list[str] = []
        if controls_ids and len(controls_ids) <= fetch_ids_limit:
            answer = await api.get_step_answer(
                combined_step_id,
                pagination={
                    "offset": 0,
                    "numRecords": min(len(controls_ids), fetch_ids_limit),
                },
            )
            ids_found = extract_record_ids(
                answer.records, preferred_key=config.id_field
            )

        intersection_ids_sample: JsonValue = list(ids_found[:50])
        intersection_ids: JsonValue = (
            list(ids_found) if len(controls_ids) <= fetch_ids_limit else None
        )
        return {
            "controlsCount": len([x for x in controls_ids if str(x).strip()]),
            "intersectionCount": total,
            "intersectionIdsSample": intersection_ids_sample,
            "intersectionIds": intersection_ids,
            "targetStepId": target_step_id,
            "targetEstimatedSize": target_total,
        }
    finally:
        await delete_temp_strategy(api, temp_strategy_id)


async def _cleanup_internal_control_test_strategies(
    api: StrategyAPI, config: IntersectionConfig
) -> None:
    """Delete internal control-test strategies left by an interrupted run.

    A control test creates a temporary strategy under the current user
    account.
    """
    try:
        strategies = await api.list_strategies()
    except VEuPathDBError as exc:
        logger.warning(
            "Failed to list strategies for control-test cleanup", error=str(exc)
        )
        return
    await cleanup_internal_control_test_strategies(api, strategies, config)


async def run_positive_negative_controls(
    config: IntersectionConfig,
    *,
    positive_controls: list[str] | None = None,
    negative_controls: list[str] | None = None,
    skip_cleanup: bool = False,
) -> ControlTestResult:
    """Run the positive and the negative controls against one search config.

    Each control set creates its own target step, because WDK deletes every
    step of a strategy together with the strategy.
    """
    if not skip_cleanup:
        cleanup_api = get_strategy_api(config.site_id)
        await _cleanup_internal_control_test_strategies(cleanup_api, config)

    target = ControlTargetData(
        search_name=config.target_search_name,
        parameters=config.target_parameters or {},
    )
    result = ControlTestResult(
        site_id=config.site_id,
        record_type=config.record_type,
        target=target,
    )

    pos = [str(x).strip() for x in (positive_controls or []) if str(x).strip()]
    neg = [str(x).strip() for x in (negative_controls or []) if str(x).strip()]

    if pos:
        pos_payload = await _run_intersection_control(config, controls_ids=pos)
        pos_data = ControlSetData.model_validate(pos_payload)

        # Capture target info from the first successful run.
        target.step_id = pos_data.target_step_id
        target.estimated_size = pos_data.target_estimated_size

        found = summarize_intersection(pos_payload)
        recovered = found.found_ids
        missing = [x for x in pos if x not in recovered] if found.ids_were_read else []
        pos_data.missing_ids_sample = missing[:50]
        pos_data.recall = found.intersection_count / len(pos)
        result.positive = pos_data

    if neg:
        neg_payload = await _run_intersection_control(config, controls_ids=neg)
        neg_data = ControlSetData.model_validate(neg_payload)

        # Fill target info if not set yet (e.g. no positive controls).
        if target.step_id is None:
            target.step_id = neg_data.target_step_id
            target.estimated_size = neg_data.target_estimated_size

        hits = summarize_intersection(neg_payload)
        neg_data.unexpected_hits_sample = sorted(hits.found_ids)[:50]
        neg_data.false_positive_rate = hits.intersection_count / len(neg)
        result.negative = neg_data

    return result

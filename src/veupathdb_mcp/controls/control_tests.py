"""Positive/negative control test helpers for planning mode.

These helpers run *temporary* WDK steps/strategies to evaluate whether known
positive controls are returned and known negative controls are excluded.
"""

from dataclasses import dataclass

from veupathdb import get_logger
from veupathdb.domain import SearchContext
from veupathdb.domain.parameters import ParamValue, StringValue
from veupathdb.errors import VEuPathDBError
from veupathdb.wdk import (
    CombinedStepSpec,
    NewStepSpec,
    StrategyAPI,
    WDKDatasetConfigIdList,
    WDKDatasetIdListContent,
    WDKParameter,
    WDKSearchConfig,
    WDKStepTree,
    encode_params,
    get_strategy_api,
)

from veupathdb_mcp.catalog.searches import find_record_type_for_search
from veupathdb_mcp.controls.control_helpers import (
    _encode_id_list,
    _get_total_count_for_step,
    cleanup_internal_control_test_strategies,
    delete_temp_strategy,
)
from veupathdb_mcp.controls.control_types import (
    ControlTargetData,
    ControlTestResult,
    IntersectionConfig,
    NegativeControls,
    PositiveControls,
)
from veupathdb_mcp.wdk.helpers import extract_record_ids
from veupathdb_mcp.wdk.step_report_filters import step_view_filters, view_filters_for

__all__ = [
    "resolve_controls_param_type",
    "run_positive_negative_controls",
    "run_step_control_tests",
]

logger = get_logger(__name__)

_STEP_PAGE_RECORDS = 50000


def _positive_controls(
    controls: list[str], returned: set[str]
) -> PositiveControls | None:
    """File each positive control as recovered or missed, or None without one."""
    ids = set(controls)
    if not ids:
        return None
    return PositiveControls(
        recovered_ids=sorted(ids & returned), missed_ids=sorted(ids - returned)
    )


def _negative_controls(
    controls: list[str], returned: set[str]
) -> NegativeControls | None:
    """File each negative control as admitted or excluded, or None without one."""
    ids = set(controls)
    if not ids:
        return None
    return NegativeControls(
        admitted_ids=sorted(ids & returned), excluded_ids=sorted(ids - returned)
    )


async def _read_step_ids(api: StrategyAPI, step_id: int) -> tuple[set[str], int]:
    """Read every record of a step, one page at a time, and the step's count."""
    view_filters = await step_view_filters(api, step_id)
    ids: set[str] = set()
    offset = 0
    while True:
        answer = await api.get_step_answer(
            step_id,
            pagination={"offset": offset, "numRecords": _STEP_PAGE_RECORDS},
            view_filters=view_filters,
        )
        ids.update(record.display_name for record in answer.records)
        offset += len(answer.records)
        count = answer.meta.records_returned()
        if not answer.records or offset >= count:
            return ids, count


async def run_step_control_tests(
    site_id: str,
    wdk_step_id: int,
    positive_controls: list[str] | None = None,
    negative_controls: list[str] | None = None,
) -> ControlTestResult:
    """File every control by whether an already-built step returns it."""
    result_ids, count = await _read_step_ids(get_strategy_api(site_id), wdk_step_id)
    return ControlTestResult(
        site_id=site_id,
        target=ControlTargetData(step_id=wdk_step_id, estimated_size=count),
        positive=_positive_controls(positive_controls or [], result_ids),
        negative=_negative_controls(negative_controls or [], result_ids),
    )


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


@dataclass(frozen=True)
class _IntersectionRun:
    """The target step one intersection created, and the control ids it returned."""

    target_step_id: int
    target_estimated_size: int | None
    returned_ids: set[str]


async def _run_intersection_control(
    config: IntersectionConfig,
    controls_ids: list[str],
) -> _IntersectionRun:
    """Run a single control intersection and read every id it returned.

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
        # The intersection lies inside the controls step, so one read of
        # every record reads no more records than the call names controls.
        answer = await api.get_step_answer(
            combined_step_id,
            pagination={"offset": 0, "numRecords": -1},
            view_filters=view_filters_for(target_rt),
        )
        return _IntersectionRun(
            target_step_id=target_step_id,
            target_estimated_size=target_total,
            returned_ids=set(
                extract_record_ids(answer.records, preferred_key=config.id_field)
            ),
        )
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
        pos_run = await _run_intersection_control(config, controls_ids=pos)
        target.step_id = pos_run.target_step_id
        target.estimated_size = pos_run.target_estimated_size
        result.positive = _positive_controls(pos, pos_run.returned_ids)

    if neg:
        neg_run = await _run_intersection_control(config, controls_ids=neg)
        if target.step_id is None:
            target.step_id = neg_run.target_step_id
            target.estimated_size = neg_run.target_estimated_size
        result.negative = _negative_controls(neg, neg_run.returned_ids)

    return result

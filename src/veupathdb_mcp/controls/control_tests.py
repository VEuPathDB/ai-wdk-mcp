"""Control tests: file known positive and negative genes by what a step returns.

A search test runs temporary WDK steps inside an internal strategy it deletes.
"""

from collections.abc import Set

from veupathdb import get_logger
from veupathdb.domain import SearchContext
from veupathdb.domain.parameters import ParamValue, StringValue
from veupathdb.domain.strategy import DEFAULT_COMBINE_OPERATOR, CombineOp
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
    ControlsDataset,
    ControlsSearch,
    ControlTargetData,
    ControlTestResult,
    Intersection,
    IntersectionConfig,
    IntersectionTarget,
    NegativeControls,
    PositiveControls,
)
from veupathdb_mcp.wdk.helpers import extract_record_ids
from veupathdb_mcp.wdk.step_report_filters import step_view_filters, view_filters_for

__all__ = [
    "intersect_with_controls",
    "resolve_controls_param_type",
    "run_positive_negative_controls",
    "run_step_control_tests",
    "upload_controls",
]

logger = get_logger(__name__)

_STEP_PAGE_RECORDS = 50000


def _positive_controls(
    controls: list[str], returned: Set[str]
) -> PositiveControls | None:
    """File each positive control as recovered or missed, or None without one."""
    return PositiveControls.filed(controls, returned) if controls else None


def _negative_controls(
    controls: list[str], returned: Set[str]
) -> NegativeControls | None:
    """File each negative control as admitted or excluded, or None without one."""
    return NegativeControls.filed(controls, returned) if controls else None


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


async def upload_controls(
    api: StrategyAPI, search: ControlsSearch, ids: list[str]
) -> ControlsDataset:
    """Put the control ids where the controls search reads them, once per run.

    An input-dataset parameter reads an uploaded dataset. Any other parameter
    reads the ids as text.
    """
    param_type = await resolve_controls_param_type(
        api, search.record_type, search.search_name, search.param_name
    )
    parameters: dict[str, ParamValue] = dict(search.extra_parameters)
    if param_type == "input-dataset":
        dataset_id = await api.create_dataset(
            WDKDatasetConfigIdList(
                source_type="idList",
                source_content=WDKDatasetIdListContent(ids=ids),
            )
        )
        parameters[search.param_name] = StringValue(value=str(dataset_id))
    else:
        parameters[search.param_name] = StringValue(
            value=_encode_id_list(ids, search.value_format)
        )
    return ControlsDataset(
        search_name=search.search_name,
        parameters=parameters,
        record_type=search.record_type,
    )


async def intersect_with_controls(
    api: StrategyAPI,
    target: IntersectionTarget,
    dataset: ControlsDataset,
    *,
    strategy_name: str,
    boolean_operator: CombineOp = DEFAULT_COMBINE_OPERATOR,
    id_field: str | None = None,
) -> Intersection:
    """Combine a target tree with the controls and read every control it returns.

    Six calls: the controls step, the combine, the internal strategy, the
    target's count, the combine's answer, and the delete.
    """
    controls_step = await api.create_step(
        NewStepSpec(
            search_name=dataset.search_name,
            search_config=WDKSearchConfig(parameters=encode_params(dataset.parameters)),
            custom_name="Controls",
        ),
        record_type=dataset.record_type,
    )
    combined_step = await api.create_combined_step(
        CombinedStepSpec(
            primary_step_id=target.tree.step_id,
            secondary_step_id=controls_step.id,
            boolean_operator=boolean_operator,
            custom_name=f"{boolean_operator} controls",
        ),
        record_type=target.record_type,
    )
    # WDK counts a step only inside a strategy (WDK-STEP-005).
    root = WDKStepTree(
        step_id=combined_step.id,
        primary_input=target.tree,
        secondary_input=WDKStepTree(step_id=controls_step.id),
    )
    temp_strategy_id: int | None = None
    try:
        created = await api.create_strategy(
            step_tree=root, name=strategy_name, description=None, is_internal=True
        )
        temp_strategy_id = created.id
        target_count = await _get_total_count_for_step(api, target.tree.step_id)
        # The intersection lies inside the controls step, so one read of
        # every record reads no more records than the call names controls.
        answer = await api.get_step_answer(
            combined_step.id,
            pagination={"offset": 0, "numRecords": -1},
            view_filters=view_filters_for(target.record_type),
        )
        return Intersection(
            target_count=target_count,
            returned_ids=frozenset(
                extract_record_ids(answer.records, preferred_key=id_field)
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


def _cleaned(ids: list[str] | None) -> list[str]:
    return [str(x).strip() for x in (ids or []) if str(x).strip()]


async def run_positive_negative_controls(
    config: IntersectionConfig,
    *,
    positive_controls: list[str] | None = None,
    negative_controls: list[str] | None = None,
    skip_cleanup: bool = False,
) -> ControlTestResult:
    """Run the positive and the negative controls against one search config.

    One dataset holds both sets and one intersection reads them, so a run
    costs ten WDK calls with its cleanup list.
    """
    api = get_strategy_api(config.site_id)
    if not skip_cleanup:
        await _cleanup_internal_control_test_strategies(api, config)

    target = ControlTargetData(
        search_name=config.target_search_name,
        parameters=config.target_parameters or {},
    )
    result = ControlTestResult(
        site_id=config.site_id,
        record_type=config.record_type,
        target=target,
    )
    pos = _cleaned(positive_controls)
    neg = _cleaned(negative_controls)
    if not pos and not neg:
        return result

    # A search has one correct record type, which the catalog knows. A gene
    # search lives under "transcript".
    target_rt = await find_record_type_for_search(
        SearchContext(config.site_id, config.record_type, config.target_search_name)
    )
    controls_rt = await find_record_type_for_search(
        SearchContext(config.site_id, config.record_type, config.controls_search_name)
    )
    dataset = await upload_controls(
        api,
        ControlsSearch(
            search_name=config.controls_search_name,
            param_name=config.controls_param_name,
            record_type=controls_rt,
            value_format=config.controls_value_format,
            extra_parameters=dict(config.controls_extra_parameters or {}),
        ),
        list(dict.fromkeys(pos + neg)),
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
    run = await intersect_with_controls(
        api,
        IntersectionTarget(
            tree=WDKStepTree(step_id=target_step.id), record_type=target_rt
        ),
        dataset,
        strategy_name=config.internal_strategy_name,
        boolean_operator=config.boolean_operator,
        id_field=config.id_field,
    )
    target.step_id = target_step.id
    target.estimated_size = run.target_count
    result.positive = _positive_controls(pos, run.returned_ids)
    result.negative = _negative_controls(neg, run.returned_ids)
    return result

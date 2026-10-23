"""Control tests: file known positive and negative genes by what a step returns.

Each test runs temporary WDK steps inside an internal strategy it deletes.
"""

from collections.abc import Set

from veupathdb import get_logger
from veupathdb.domain import SearchContext
from veupathdb.domain.parameters import ParamValue, StringValue
from veupathdb.domain.strategy import CombineOp
from veupathdb.errors import DataParsingError, ValidationError, VEuPathDBError
from veupathdb.wdk import (
    CombinedStepSpec,
    NewStepSpec,
    StrategyAPI,
    WDKDatasetConfigIdList,
    WDKDatasetIdListContent,
    WDKParameter,
    WDKSearchConfig,
    WDKStep,
    WDKStepTree,
    encode_params,
    get_strategy_api,
    walk_wdk_step_tree,
)

from veupathdb_mcp.catalog.searches import listed_record_type
from veupathdb_mcp.controls.account_writes import RunWrites, run_writes
from veupathdb_mcp.controls.control_helpers import (
    _encode_id_list,
    _get_total_count_for_step,
    delete_leftover_strategies,
)
from veupathdb_mcp.controls.control_types import (
    DEFAULT_CONTROL_TEST_STRATEGY_NAME,
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
from veupathdb_mcp.wdk import TRANSCRIPTS_PER_GENE
from veupathdb_mcp.wdk.helpers import extract_record_ids
from veupathdb_mcp.wdk.step_report_filters import view_filters_for

__all__ = [
    "intersect_with_controls",
    "resolve_controls_param_type",
    "run_positive_negative_controls",
    "run_step_control_tests",
    "upload_controls",
]

logger = get_logger(__name__)

_GENE_IDS = ControlsSearch()


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


def _tested_record_type(step: WDKStep, controls: ControlsSearch) -> str:
    if step.record_class_name != controls.record_type:
        raise ValidationError(
            title="Controls search reads another record type",
            detail=(
                f"step {step.id} returns {step.record_class_name} records and "
                f"{controls.search_name} reads {controls.record_type} records"
            ),
        )
    return controls.record_type


def _strategy_of(step: WDKStep) -> int:
    if step.strategy_id is None:
        raise ValidationError(
            title="Step is not in a strategy",
            detail=f"step {step.id} belongs to no strategy, so WDK cannot copy it",
        )
    return step.strategy_id


async def _copied_subtree(
    api: StrategyAPI, writes: RunWrites, step_id: int, strategy_id: int
) -> WDKStepTree:
    strategy = await api.get_strategy(strategy_id)
    originals = walk_wdk_step_tree(strategy.step_tree)
    copies = walk_wdk_step_tree(
        await writes.steps(api.get_duplicated_step_tree(strategy_id))
    )
    if len(originals) != len(copies):
        msg = f"the copy of strategy {strategy_id} has another shape"
        raise DataParsingError(msg)
    matches = [
        copy
        for original, copy in zip(originals, copies, strict=True)
        if original.step_id == step_id
    ]
    if not matches:
        msg = f"step {step_id} is not in the tree of strategy {strategy_id}"
        raise DataParsingError(msg)
    kept = {node.step_id for node in walk_wdk_step_tree(matches[0])}
    await writes.delete_steps(
        [node.step_id for node in copies if node.step_id not in kept]
    )
    return matches[0]


async def run_step_control_tests(
    site_id: str,
    wdk_step_id: int,
    positive_controls: list[str] | None = None,
    negative_controls: list[str] | None = None,
    *,
    controls: ControlsSearch = _GENE_IDS,
) -> ControlTestResult:
    """File every control by whether an already-built step returns it."""
    api = get_strategy_api(site_id)
    target = ControlTargetData(step_id=wdk_step_id)
    result = ControlTestResult(site_id=site_id, target=target)
    pos = _cleaned(positive_controls)
    neg = _cleaned(negative_controls)
    if not pos and not neg:
        target.estimated_size = await _get_total_count_for_step(api, wdk_step_id)
        return result

    step = await api.find_step(wdk_step_id)
    record_type = _tested_record_type(step, controls)
    strategy_id = _strategy_of(step)
    await _sweep_leftovers(api, site_id, DEFAULT_CONTROL_TEST_STRATEGY_NAME)
    dataset = await upload_controls(api, controls, list(dict.fromkeys(pos + neg)))
    async with run_writes(api) as writes:
        tree = await _copied_subtree(api, writes, wdk_step_id, strategy_id)
        run = await intersect_with_controls(
            api,
            writes,
            IntersectionTarget(tree=tree, record_type=record_type),
            dataset,
            strategy_name=DEFAULT_CONTROL_TEST_STRATEGY_NAME,
        )
    target.estimated_size = run.target_count
    result.positive = _positive_controls(pos, run.returned_ids)
    result.negative = _negative_controls(neg, run.returned_ids)
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
        id_count=len(ids),
    )


def _answer_bound(dataset: ControlsDataset) -> int:
    return dataset.id_count * TRANSCRIPTS_PER_GENE


async def intersect_with_controls(
    api: StrategyAPI,
    writes: RunWrites,
    target: IntersectionTarget,
    dataset: ControlsDataset,
    *,
    strategy_name: str,
    id_field: str | None = None,
) -> Intersection:
    """Intersect a target tree with the controls and read every control it returns.

    Five calls: the controls step, the combine, the internal strategy, the
    target's count and the combine's answer. ``writes`` deletes what they made.
    """
    controls_step = await writes.step(
        api.create_step(
            NewStepSpec(
                search_name=dataset.search_name,
                search_config=WDKSearchConfig(
                    parameters=encode_params(dataset.parameters)
                ),
                custom_name="Controls",
            ),
            record_type=dataset.record_type,
        )
    )
    combined_step = await writes.step(
        api.create_combined_step(
            CombinedStepSpec(
                primary_step_id=target.tree.step_id,
                secondary_step_id=controls_step,
                boolean_operator=CombineOp.INTERSECT,
                custom_name=f"{CombineOp.INTERSECT} controls",
            ),
            record_type=target.record_type,
        )
    )
    # WDK counts a step only inside a strategy (WDK-STEP-005).
    await writes.strategy(
        WDKStepTree(
            step_id=combined_step,
            primary_input=target.tree,
            secondary_input=WDKStepTree(step_id=controls_step),
        ),
        strategy_name,
    )
    target_count = await _get_total_count_for_step(api, target.tree.step_id)
    bound = _answer_bound(dataset)
    answer = await api.get_step_answer(
        combined_step,
        pagination={"offset": 0, "numRecords": bound + 1},
        view_filters=view_filters_for(target.record_type),
    )
    if len(answer.records) > bound:
        raise ValidationError(
            title="Controls answer holds more records than its ids allow",
            detail=(
                f"{dataset.search_name} answered more than {bound} records for "
                f"{dataset.id_count} control ids"
            ),
        )
    return Intersection(
        target_count=target_count,
        returned_ids=frozenset(
            extract_record_ids(answer.records, preferred_key=id_field)
        ),
    )


async def _sweep_leftovers(api: StrategyAPI, site_id: str, strategy_name: str) -> None:
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
    await delete_leftover_strategies(
        api, strategies, site_id=site_id, strategy_name=strategy_name
    )


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
        await _sweep_leftovers(api, config.site_id, config.internal_strategy_name)

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
    target_rt = await listed_record_type(
        SearchContext(config.site_id, config.record_type, config.target_search_name)
    )
    controls_rt = await listed_record_type(
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
    async with run_writes(api) as writes:
        target_step = await writes.step(
            api.create_step(
                NewStepSpec(
                    search_name=config.target_search_name,
                    search_config=WDKSearchConfig(
                        parameters=encode_params(config.target_parameters),
                    ),
                    custom_name="Target",
                ),
                record_type=target_rt,
            )
        )
        run = await intersect_with_controls(
            api,
            writes,
            IntersectionTarget(
                tree=WDKStepTree(step_id=target_step), record_type=target_rt
            ),
            dataset,
            strategy_name=config.internal_strategy_name,
            id_field=config.id_field,
        )
    target.step_id = target_step
    target.estimated_size = run.target_count
    result.positive = _positive_controls(pos, run.returned_ids)
    result.negative = _negative_controls(neg, run.returned_ids)
    return result

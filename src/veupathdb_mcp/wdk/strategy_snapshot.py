"""The strategy AST a saved WDK strategy converts into.

Conversion is pure except for the canonicalization pass, which reads each
search's parameter specs from WDK.
"""

from pydantic import BaseModel, ConfigDict
from veupathdb import get_logger
from veupathdb.domain.strategy import (
    ColocationParams,
    CombineOp,
    StepFilter,
    StepSettings,
    StepValidation,
    StrategyAst,
    StrategyStepNode,
    parse_op,
    walk,
)
from veupathdb.errors import DataParsingError
from veupathdb.wdk import (
    BOOLEAN_OPERATOR_PARAM,
    BOOLEAN_SEARCH_PREFIX,
    StrategyAPI,
    WDKSearch,
    WDKStep,
    WDKStepTree,
    WDKStrategyDetails,
    walk_wdk_step_tree,
)

from veupathdb_mcp.wdk.param_decoding import decode_wire_parameters, load_search_spec

__all__ = ["WireStep", "build_snapshot_from_wdk", "canonicalize_synced_parameters"]

logger = get_logger(__name__)


class WireStep(BaseModel):
    model_config = ConfigDict(frozen=True)

    record_class: str | None
    parameters: dict[str, str]


_SPAN_LOGIC = "GenesBySpanLogic"


def _combine_of(step: WDKStep) -> tuple[CombineOp, ColocationParams | None]:
    parameters = step.search_config.parameters
    if step.search_name == _SPAN_LOGIC:
        return CombineOp.COLOCATE, ColocationParams.from_wdk_params(parameters)
    if not step.search_name.startswith(BOOLEAN_SEARCH_PREFIX):
        msg = (
            f"Combine step {step.id} runs {step.search_name}, which is neither "
            f"a boolean search nor {_SPAN_LOGIC}"
        )
        raise DataParsingError(msg)
    if BOOLEAN_OPERATOR_PARAM not in parameters:
        msg = (
            f"Combine step {step.id} has no {BOOLEAN_OPERATOR_PARAM} in "
            f"searchConfig.parameters (keys: {list(parameters.keys())})"
        )
        raise DataParsingError(msg)
    value = parameters[BOOLEAN_OPERATOR_PARAM]
    try:
        return parse_op(value), None
    except ValueError as exc:
        msg = (
            f"Combine step {step.id} has {BOOLEAN_OPERATOR_PARAM} {value!r}, "
            "which is not a combine operator"
        )
        raise DataParsingError(msg) from exc


def runs_a_combine(step: WDKStep) -> bool:
    return step.search_name == _SPAN_LOGIC or step.search_name.startswith(
        BOOLEAN_SEARCH_PREFIX
    )


def settings_on_the_wire(step: WDKStep, *, combine: bool) -> StepSettings:
    config = step.search_config
    operator, colocation = _combine_of(step) if combine else (None, None)
    return StepSettings(
        operator=operator,
        colocation_params=colocation,
        filters=[
            StepFilter.model_validate(f.model_dump(by_alias=True, mode="json"))
            for f in config.filters
        ],
        wdk_weight=config.wdk_weight or None,
    )


def _build_node(
    tree_node: WDKStepTree,
    steps: dict[str, WDKStep],
    wire_by_step_id: dict[str, WireStep],
) -> StrategyStepNode:
    """Build a step node tree from typed WDK models.

    ``walk_wdk_step_tree`` yields every input before the step that consumes it,
    so each node finds its inputs already built. Parameter values stay empty
    because the WDK wire form has no param-spec context; wire parameters go
    into the sidecar dict for later decoding.
    """
    built: dict[int, StrategyStepNode] = {}
    for node in walk_wdk_step_tree(tree_node):
        built[node.step_id] = _node_of(node, built, steps, wire_by_step_id)
    return built[tree_node.step_id]


def _node_of(
    node: WDKStepTree,
    built: dict[int, StrategyStepNode],
    steps: dict[str, WDKStep],
    wire_by_step_id: dict[str, WireStep],
) -> StrategyStepNode:
    """The AST node for one wire node, over the inputs already built."""
    step = steps.get(str(node.step_id))
    if step is None:
        msg = (
            f"Step {node.step_id} not found in WDK steps dict "
            f"(available keys: {list(steps.keys())[:20]})"
        )
        raise DataParsingError(msg)

    local_id = str(node.step_id)
    secondary = (
        built[node.secondary_input.step_id]
        if node.primary_input is not None and node.secondary_input is not None
        else None
    )
    settings = settings_on_the_wire(step, combine=secondary is not None)
    if secondary is None:
        wire_by_step_id[local_id] = WireStep(
            record_class=step.record_class_name,
            parameters=dict(step.search_config.parameters),
        )
    return StrategyStepNode(
        search_name=step.search_name,
        operator=settings.operator,
        colocation_params=settings.colocation_params,
        filters=settings.filters,
        wdk_weight=settings.wdk_weight,
        primary_input=(
            built[node.primary_input.step_id]
            if node.primary_input is not None
            else None
        ),
        secondary_input=secondary,
        display_name=step.custom_name or step.display_name or None,
        expanded_name=(
            step.expanded_name if secondary is not None and step.expanded else None
        ),
        id=local_id,
    )


def _extract_wdk_metadata(
    root: StrategyStepNode,
    wdk_steps: dict[str, WDKStep],
) -> tuple[dict[str, int], dict[str, int], dict[str, StepValidation]]:
    """Extract step counts, WDK step ids and WDK's own validation from the tree."""
    step_counts: dict[str, int] = {}
    wdk_step_ids: dict[str, int] = {}
    validations: dict[str, StepValidation] = {}
    for step in walk(root):
        if not step.id.isdigit():
            continue
        wdk_id = int(step.id)
        wdk_step_ids[step.id] = wdk_id
        wdk_step = wdk_steps.get(str(wdk_id))
        if wdk_step is not None and wdk_step.estimated_size is not None:
            step_counts[step.id] = wdk_step.estimated_size
        if wdk_step is not None and wdk_step.validation is not None:
            validations[step.id] = wdk_step.validation
    return step_counts, wdk_step_ids, validations


def build_snapshot_from_wdk(
    wdk_strategy: WDKStrategyDetails,
) -> tuple[StrategyAst, dict[str, WireStep]]:
    """Convert a typed WDK strategy into a strategy AST plus a wire-params sidecar.

    Wire-form parameters are returned separately because they need a WDK
    search spec to decode into typed values.
    """
    record_type = wdk_strategy.record_class_name or ""
    if not record_type.strip():
        msg = "WDK strategy is missing a valid 'recordClassName'"
        raise DataParsingError(msg)
    record_type = record_type.strip()

    wire_by_step_id: dict[str, WireStep] = {}
    root = _build_node(wdk_strategy.step_tree, wdk_strategy.steps, wire_by_step_id)

    step_counts, wdk_step_ids, validations = _extract_wdk_metadata(
        root, wdk_strategy.steps
    )
    payload = StrategyAst(
        record_type=record_type,
        root=root,
        name=wdk_strategy.name or None,
        description=wdk_strategy.description or None,
        step_counts=step_counts or None,
        wdk_step_ids=wdk_step_ids or None,
        step_validations=validations or None,
    )
    return payload, wire_by_step_id


async def canonicalize_synced_parameters(
    payload: StrategyAst,
    api: StrategyAPI,
    wire_by_step_id: dict[str, WireStep],
) -> None:
    """Read each step's wire parameters against its WDK search spec, in place.

    A value no kind reads, and every value of a step whose spec cannot be
    read, is held as WDK holds it. Only a declared input-step value is left
    out: it is the wiring WDK's step tree carries.
    """
    spec_cache: dict[tuple[str, str], WDKSearch | None] = {}

    for step in walk(payload.root):
        if step.infer_kind() == "combine":
            continue
        search_name = step.search_name
        wire = wire_by_step_id.get(step.id)
        if not search_name or wire is None or not wire.parameters:
            continue
        record_type = wire.record_class
        cache_key = (record_type or "", search_name)
        if record_type is not None and cache_key not in spec_cache:
            spec_cache[cache_key] = await load_search_spec(
                api, record_type, search_name, wire.parameters
            )
        step.parameters = decode_wire_parameters(
            spec_cache.get(cache_key), wire.parameters
        )

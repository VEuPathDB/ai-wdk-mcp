"""The strategy AST a saved WDK strategy converts into.

Conversion is pure except for the canonicalization pass, which reads each
search's parameter specs from WDK.
"""

from veupathdb import get_logger
from veupathdb.domain.parameters import ParameterCanonicalizer, ParamKind, as_param_kind
from veupathdb.domain.strategy import StrategyAst, StrategyStepNode, parse_op, walk
from veupathdb.errors import DataParsingError, VEuPathDBError
from veupathdb.wdk import (
    StrategyAPI,
    WDKSearch,
    WDKStep,
    WDKStepTree,
    WDKStrategyDetails,
    decode_params,
    walk_wdk_step_tree,
)

from veupathdb_mcp.catalog.param_adapters import adapt_param_specs_from_search
from veupathdb_mcp.catalog.search_context import get_search_params_under_context

__all__ = ["build_snapshot_from_wdk", "canonicalize_synced_parameters"]

logger = get_logger(__name__)


def _extract_operator(parameters: dict[str, str]) -> str | None:
    """Find the boolean operator in a combine step's parameter dict."""
    for key, value in parameters.items():
        if "operator" in key.lower():
            return value
    return None


def _resolve_expanded_reference(
    combine_step: WDKStep,
    secondary_node: StrategyStepNode,
    steps: dict[str, WDKStep],
) -> tuple[int | None, str | None]:
    """Map the WDK expanded reference onto the secondary input.

    WDK marks the secondary input of a combine as expanded when that branch
    comes from a saved strategy.
    """
    if not combine_step.expanded:
        return (None, None)
    secondary_step_id = int(secondary_node.id) if secondary_node.id.isdigit() else None
    if secondary_step_id is None:
        return (None, None)
    secondary_wdk = steps.get(str(secondary_step_id))
    if secondary_wdk is None or secondary_wdk.strategy_id is None:
        return (None, None)
    return (secondary_wdk.strategy_id, combine_step.expanded_name)


def _build_node(
    tree_node: WDKStepTree,
    steps: dict[str, WDKStep],
    wire_by_step_id: dict[str, dict[str, str]],
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
    wire_by_step_id: dict[str, dict[str, str]],
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
    display_name = step.custom_name or step.display_name or None
    wire_parameters = step.search_config.parameters

    if node.primary_input is not None and node.secondary_input is not None:
        right = built[node.secondary_input.step_id]
        raw_operator = _extract_operator(wire_parameters)
        if raw_operator is None:
            msg = (
                f"Combine step {node.step_id} has no boolean operator in "
                f"searchConfig.parameters (keys: {list(wire_parameters.keys())})"
            )
            raise DataParsingError(msg)
        expanded_strategy_id, expanded_name = _resolve_expanded_reference(
            step, right, steps
        )
        return StrategyStepNode(
            search_name=step.search_name,
            operator=parse_op(raw_operator),
            primary_input=built[node.primary_input.step_id],
            secondary_input=right,
            display_name=display_name,
            expanded_strategy_id=expanded_strategy_id,
            expanded_name=expanded_name,
            id=local_id,
        )
    wire_by_step_id[local_id] = dict(wire_parameters)
    return StrategyStepNode(
        search_name=step.search_name,
        primary_input=(
            built[node.primary_input.step_id]
            if node.primary_input is not None
            else None
        ),
        display_name=display_name,
        id=local_id,
    )


def _extract_wdk_metadata(
    root: StrategyStepNode,
    wdk_steps: dict[str, WDKStep],
) -> tuple[dict[str, int], dict[str, int]]:
    """Extract step counts and WDK step ids from the tree."""
    step_counts: dict[str, int] = {}
    wdk_step_ids: dict[str, int] = {}
    for step in walk(root):
        if not step.id.isdigit():
            continue
        wdk_id = int(step.id)
        wdk_step_ids[step.id] = wdk_id
        wdk_step = wdk_steps.get(str(wdk_id))
        if wdk_step is not None and wdk_step.estimated_size is not None:
            step_counts[step.id] = wdk_step.estimated_size
    return step_counts, wdk_step_ids


def build_snapshot_from_wdk(
    wdk_strategy: WDKStrategyDetails,
) -> tuple[StrategyAst, dict[str, dict[str, str]]]:
    """Convert a typed WDK strategy into a strategy AST plus a wire-params sidecar.

    Wire-form parameters are returned separately because they need a WDK
    search spec to decode into typed values.
    """
    record_type = wdk_strategy.record_class_name or ""
    if not record_type.strip():
        msg = "WDK strategy is missing a valid 'recordClassName'"
        raise DataParsingError(msg)
    record_type = record_type.strip()

    wire_by_step_id: dict[str, dict[str, str]] = {}
    root = _build_node(wdk_strategy.step_tree, wdk_strategy.steps, wire_by_step_id)

    step_counts, wdk_step_ids = _extract_wdk_metadata(root, wdk_strategy.steps)
    payload = StrategyAst(
        record_type=record_type,
        root=root,
        name=wdk_strategy.name or None,
        description=wdk_strategy.description or None,
        step_counts=step_counts or None,
        wdk_step_ids=wdk_step_ids or None,
    )
    return payload, wire_by_step_id


async def _load_search_spec(
    api: StrategyAPI,
    record_type: str,
    search_name: str,
    context: dict[str, str],
) -> WDKSearch | None:
    """Load a search spec, narrowed by the given context. None if unreachable."""
    try:
        response = await get_search_params_under_context(
            api.client, record_type, search_name, context
        )
    except VEuPathDBError as exc:
        logger.warning(
            "Failed to load search details during WDK sync",
            record_type=record_type,
            search_name=search_name,
            error=str(exc),
        )
        return None
    return response.search_data


async def canonicalize_synced_parameters(
    payload: StrategyAst,
    api: StrategyAPI,
    wire_by_step_id: dict[str, dict[str, str]],
) -> None:
    """Decode and canonicalize wire parameters against their WDK search specs.

    Mutates the step nodes in place.
    """
    spec_cache: dict[tuple[str, str], WDKSearch | None] = {}

    for step in walk(payload.root):
        if step.infer_kind() == "combine":
            continue
        search_name = step.search_name
        record_type = payload.record_type
        wire_params = wire_by_step_id.get(step.id)

        if not search_name or not record_type or not wire_params:
            continue

        cache_key = (record_type, search_name)
        if cache_key not in spec_cache:
            spec_cache[cache_key] = await _load_search_spec(
                api,
                record_type,
                search_name,
                wire_params,
            )

        cached_search = spec_cache.get(cache_key)
        specs = adapt_param_specs_from_search(cached_search) if cached_search else {}
        if not specs:
            continue
        kinds: dict[str, ParamKind] = {
            name: as_param_kind(spec.param_type) for name, spec in specs.items()
        }
        decoded = decode_params(wire_params, kinds)
        try:
            canonicalizer = ParameterCanonicalizer(specs)
            canonical = canonicalizer.canonicalize(decoded)
        except VEuPathDBError as exc:
            logger.warning(
                "Failed to canonicalize synced parameters",
                record_type=record_type,
                search_name=search_name,
                step_id=step.id,
                error=str(exc),
            )
            continue

        step.parameters = canonical

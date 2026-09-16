"""The wire parameters of one WDK step, decoded against its own search spec."""

from veupathdb import get_logger
from veupathdb.domain.parameters import (
    ParameterCanonicalizer,
    ParamKind,
    ParamValue,
    as_param_kind,
)
from veupathdb.errors import VEuPathDBError
from veupathdb.wdk import StrategyAPI, WDKSearch, decode_params

from veupathdb_mcp.catalog.param_adapters import adapt_param_specs_from_search
from veupathdb_mcp.catalog.search_context import get_search_params_under_context

logger = get_logger(__name__)

__all__ = ["decode_wire_parameters", "load_search_spec"]


async def load_search_spec(
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


def decode_wire_parameters(
    search: WDKSearch,
    wire: dict[str, str],
) -> dict[str, ParamValue] | None:
    """Canonical typed values for ``wire``, or None when the spec cannot decode it.

    An empty mapping states that the search declares parameters and the step
    sets none of them.
    """
    specs = adapt_param_specs_from_search(search)
    if not specs:
        return None
    kinds: dict[str, ParamKind] = {
        name: as_param_kind(spec.param_type) for name, spec in specs.items()
    }
    try:
        return ParameterCanonicalizer(specs).canonicalize(decode_params(wire, kinds))
    except VEuPathDBError as exc:
        logger.warning(
            "Failed to canonicalize wire parameters",
            search_name=search.url_segment,
            error=str(exc),
        )
        return None

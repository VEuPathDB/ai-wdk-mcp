"""The wire parameters of one WDK step, decoded against its own search spec."""

from veupathdb import get_logger
from veupathdb.domain.parameters import ParameterCanonicalizer, ParamValue
from veupathdb.errors import VEuPathDBError
from veupathdb.wdk import StrategyAPI, WDKSearch

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
    search: WDKSearch | None, wire: dict[str, str]
) -> dict[str, ParamValue]:
    """The values ``wire`` holds, each read as its parameter's kind, never refused.

    With no search spec, every value is held as WDK holds it.
    """
    specs = adapt_param_specs_from_search(search) if search is not None else {}
    return ParameterCanonicalizer(specs).held(wire)

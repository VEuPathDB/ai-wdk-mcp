"""WDK parameter fetching, caching, and expansion."""

from collections.abc import Callable, Mapping

from veupathdb import get_logger
from veupathdb.domain import SearchContext
from veupathdb.domain.parameters import (
    ParameterCanonicalizer,
    ParamValue,
    find_input_step_param,
)
from veupathdb.errors import (
    ValidationError,
    VEuPathDBError,
    VEuPathDBErrorCode,
    WDKError,
)
from veupathdb.model import CamelModel
from veupathdb.wdk import (
    VEuPathDBClient,
    WDKParameter,
    WDKSearchResponse,
    encode_wdk_params,
    get_wdk_client,
    resolve_record_type,
)

from veupathdb_mcp.catalog.discovery_service import (
    get_discovery_service,
)
from veupathdb_mcp.catalog.param_adapters import adapt_param_specs_from_search
from veupathdb_mcp.catalog.param_discovery import fetch_search_details
from veupathdb_mcp.catalog.param_formatting import (
    ParameterInfo,
    format_param_info_typed,
)
from veupathdb_mcp.catalog.search_context import context_for_metadata_read
from veupathdb_mcp.tool_errors import ToolErrorPayload, tool_error

from .searches import find_record_type_for_search

logger = get_logger(__name__)


class SearchParametersResult(CamelModel):
    """Result of resolving search parameters for a given search."""

    search_name: str
    display_name: str
    description: str | None
    parameters: list[ParameterInfo]
    resolved_record_type: str


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def get_search_parameters(ctx: SearchContext) -> SearchParametersResult:
    """Get detailed parameter info for a specific search.

    This is intentionally defensive: WDK responses can vary by site/endpoint.
    """
    discovery = get_discovery_service()
    resolved_record_type = ctx.record_type

    record_types = await discovery.get_record_types(ctx.site_id)

    if ctx.record_type:
        resolved = resolve_record_type(record_types, ctx.record_type)
        if resolved:
            resolved_record_type = resolved

    resolved_ctx = SearchContext(ctx.site_id, resolved_record_type, ctx.search_name)
    response, resolved_record_type = await fetch_search_details(
        resolved_ctx,
        record_types=record_types,
    )

    param_info = format_param_info_typed(response.search_data.parameters or [])

    return SearchParametersResult(
        search_name=ctx.search_name,
        display_name=response.search_data.display_name or ctx.search_name,
        description=response.search_data.description,
        parameters=param_info,
        resolved_record_type=resolved_record_type,
    )


async def get_search_parameters_tool(
    ctx: SearchContext,
) -> SearchParametersResult | ToolErrorPayload:
    """Tool-friendly wrapper that returns standardized tool_error payloads."""
    try:
        return await get_search_parameters(ctx)
    except ValidationError as exc:
        code = None
        if exc.errors and isinstance(exc.errors, list) and exc.errors:
            first_error = exc.errors[0]
            if isinstance(first_error, dict):
                code_raw = first_error.get("code")
                if isinstance(code_raw, str):
                    code = code_raw
        return tool_error(
            code or VEuPathDBErrorCode.VALIDATION_ERROR,
            exc.detail or exc.title,
            errors=exc.errors,
        )


def drop_unusable_context_values(
    context: Mapping[str, ParamValue],
    canonicalize: Callable[[dict[str, ParamValue]], dict[str, ParamValue]],
) -> dict[str, ParamValue]:
    """Canonicalize context, discarding values that cannot be canonicalized.

    Context values only prime the form with what the step already had. A
    single stale one must not make the editor unopenable, which would leave
    the user no way to reach the field and fix it.
    """
    remaining = dict(context)
    while remaining:
        try:
            return canonicalize(remaining)
        except ValidationError, ValueError:
            remaining.pop(next(reversed(remaining)))
    return {}


async def expand_search_details_with_params(
    ctx: SearchContext,
    context_values: dict[str, ParamValue] | None,
) -> WDKSearchResponse:
    """Return WDK search details after applying typed context values.

    NOTE: despite the historical name, this is *not* a pure validation API; it returns
    WDK search details payload. Keep it separate from the public validation endpoint.
    """
    client = get_wdk_client(ctx.site_id)
    raw_context: dict[str, ParamValue] = context_values or {}
    response, allowed = await _load_discovery_details_and_allowed(ctx)
    filtered_context = _filter_context_values(raw_context, allowed)

    specs = adapt_param_specs_from_search(response.search_data) if response else {}

    normalized_context: dict[str, ParamValue]
    if specs:
        canonicalizer = ParameterCanonicalizer(specs)
        try:
            normalized_context = canonicalizer.canonicalize(filtered_context)
        except ValidationError:
            resolved_record_type = await find_record_type_for_search(ctx)
            fallback_response = await client.get_search_details_with_params(
                resolved_record_type,
                ctx.search_name,
                _metadata_context(encode_wdk_params(filtered_context), response),
                expand_params=True,
            )
            specs = adapt_param_specs_from_search(fallback_response.search_data)
            canonicalizer = ParameterCanonicalizer(specs)
            normalized_context = drop_unusable_context_values(
                filtered_context, canonicalizer.canonicalize
            )
    else:
        normalized_context = filtered_context

    wire_context = _metadata_context(encode_wdk_params(normalized_context), response)
    if specs:
        input_step_param = find_input_step_param(specs)
        if input_step_param:
            wire_context[input_step_param] = ""
    resolved_record_type = await find_record_type_for_search(ctx)
    return await _get_search_details_with_portal_fallback(
        site_id=ctx.site_id,
        client=client,
        record_type=resolved_record_type,
        search_name=ctx.search_name,
        context_values=wire_context,
    )


def _metadata_context(
    wire_context: dict[str, str], published: WDKSearchResponse | None
) -> dict[str, str]:
    """Completes a context with the published shape, when the shape is known."""
    if published is None:
        return wire_context
    return context_for_metadata_read(wire_context, published.search_data.parameters)


def _filter_context_values(
    raw_context: dict[str, ParamValue],
    allowed: set[str],
) -> dict[str, ParamValue]:
    """Filter context values to keys WDK recognizes for the search (best-effort).

    :param raw_context: Raw context from request.
    :param allowed: Set of allowed parameter names.
    :returns: Filtered context dict.
    """
    return (
        {key: value for key, value in raw_context.items() if key in allowed}
        if allowed
        else dict(raw_context)
    )


async def _load_discovery_details_and_allowed(
    ctx: SearchContext,
) -> tuple[WDKSearchResponse | None, set[str]]:
    """Load discovery search details + extract allowed param names (best-effort)."""
    try:
        discovery = get_discovery_service()
        response = await discovery.get_search_details(ctx, expand_params=True)
        return response, _extract_param_names_from_response(response)
    except VEuPathDBError as exc:
        logger.warning(
            "Failed to load discovery details for param resolution",
            site_id=ctx.site_id,
            record_type=ctx.record_type,
            search_name=ctx.search_name,
            error=str(exc),
        )
        return None, set()


def prefer_original_wdk_error(original: WDKError, fallback: WDKError) -> WDKError:
    """Keep the component site's error when the portal retry also fails.

    Not every component-site search exists on veupathdb.org, so the retry
    often fails with an unrelated 500. Letting that replace the original turns
    a specific, actionable message into a generic one and leaves the editor
    saying only "Failed to load parameters for this search".
    """
    return WDKError(
        f"{original.detail} (retry against the veupathdb portal also failed: "
        f"{fallback.detail})",
        original.status,
    )


async def _get_search_details_with_portal_fallback(
    *,
    site_id: str,
    client: VEuPathDBClient,
    record_type: str,
    search_name: str,
    context_values: dict[str, str],
) -> WDKSearchResponse:
    """Call WDK contextual search details, then the portal, then the static view.

    Narrowing is an enrichment, so a refusal costs vocabulary precision rather
    than the parameters themselves. Raises only when the static view fails too.
    """
    try:
        return await client.get_search_details_with_params(
            record_type,
            search_name,
            context_values,
        )
    except WDKError as site_error:
        portal_error: WDKError | None = None
        if site_id != "veupathdb":
            portal_client = get_wdk_client("veupathdb")
            try:
                return await portal_client.get_search_details_with_params(
                    record_type,
                    search_name,
                    context_values,
                )
            except WDKError as exc:
                portal_error = exc
        logger.warning(
            "WDK could not contextualize search params; using the static view",
            site_id=site_id,
            search=search_name,
            record_type=record_type,
            context_params=sorted(context_values),
            error=str(site_error),
        )
        try:
            return await client.get_search_details(
                record_type, search_name, expand_params=True
            )
        except WDKError as static_error:
            if portal_error is not None:
                raise prefer_original_wdk_error(
                    site_error, portal_error
                ) from site_error
            raise static_error from site_error


async def get_refreshed_dependent_params(
    ctx: SearchContext,
    *,
    parameter_name: str,
    context_values: dict[str, ParamValue],
) -> list[WDKParameter]:
    """Get refreshed dependent parameter vocabulary, falling back to the portal.

    Tries the site-specific WDK client first.  If that fails with a
    ``WDKError`` and the site is not already ``veupathdb``, retries against
    the portal client (``veupathdb``).
    """
    encoded = encode_wdk_params(context_values)
    client = get_wdk_client(ctx.site_id)
    try:
        return await client.get_refreshed_dependent_params(
            ctx.record_type,
            ctx.search_name,
            parameter_name,
            encoded,
        )
    except WDKError as site_error:
        if ctx.site_id == "veupathdb":
            raise
        portal_client = get_wdk_client("veupathdb")
        try:
            return await portal_client.get_refreshed_dependent_params(
                ctx.record_type,
                ctx.search_name,
                parameter_name,
                encoded,
            )
        except WDKError as portal_error:
            raise prefer_original_wdk_error(site_error, portal_error) from site_error


def _extract_param_names_from_response(response: WDKSearchResponse) -> set[str]:
    """Extract parameter names from a typed WDKSearchResponse.

    Uses ``param_names`` (always present) from the search data.
    Falls back to ``parameters`` list if param_names is empty.
    """
    search = response.search_data
    if search.param_names:
        return set(search.param_names)
    if search.parameters:
        return {p.name for p in search.parameters}
    return set()

"""veupathdb-wdk-mcp: the WDK reads and writes this deployment serves over MCP.

The server is stateless. Every tool names its site by value, and every call acts
as the credential the transport gate verified.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools import ToolResult
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.types import CallToolRequestParams, ToolAnnotations
from pydantic import BaseModel, ConfigDict
from veupathdb.logging import get_logger

from veupathdb_mcp import __version__
from veupathdb_mcp.auth import McpCredential, wdk_identity
from veupathdb_mcp.catalog import sites
from veupathdb_mcp.tool_meta import (
    MAX_CALL_SECONDS_META_KEY,
    STREAM_PART_META_KEY,
)
from veupathdb_mcp.tools.catalog_tools import (
    browse_search_categories,
    get_parameter_options,
    get_search_overview,
    list_record_types,
    list_searches,
    list_transforms,
    lookup_phyletic_codes,
    search_example_plans,
    search_for_searches,
)
from veupathdb_mcp.tools.user_tools import (
    enrich_gene_ids,
    get_ai_expression_summary,
    get_step_download_url,
    get_step_estimated_size,
    get_step_sample_records,
    lookup_gene_records,
    resolve_gene_ids_to_records,
    run_control_tests_on_search,
)

logger = get_logger(__name__)

SERVER_NAME = "veupathdb-wdk-mcp"

ENRICHMENT_PART_KIND = "data-wdk.enrichment-results"

# Five analysis types run three at a time, and each polls WDK to 300 seconds.
ENRICHMENT_MAX_CALL_SECONDS = 600
# The same control machinery the durable step variant estimates at 180 seconds.
CONTROL_TESTS_MAX_CALL_SECONDS = 180

_NO_CREDENTIAL = "The call carried no verified credential."

_INSTRUCTIONS = (
    "VEuPathDB WDK catalog, record, step and evidence tools. Every tool takes "
    "site_id. The catalog reads run on a service credential; the record, step "
    "and evidence tools act as the VEuPathDB user whose bearer the call carries."
)

_READ = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
_ADDITIVE_WRITE = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=False,
    openWorldHint=False,
)


class _SiteArgument(BaseModel):
    """The site every served tool names."""

    model_config = ConfigDict(extra="ignore")

    site_id: str


def _verified_credential() -> McpCredential:
    """The credential the transport gate verified for this call."""
    token = get_access_token()
    if token is None:
        raise ToolError(_NO_CREDENTIAL)
    return McpCredential.model_validate(token, from_attributes=True)


class WdkIdentity(Middleware):
    """Runs every tool call as the credential the gate verified."""

    async def on_call_tool(
        self,
        context: MiddlewareContext[CallToolRequestParams],
        call_next: CallNext[CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        with wdk_identity(_verified_credential()):
            return await call_next(context)


class SiteGuard(Middleware):
    """Refuses a call that names a site this deployment does not serve."""

    async def on_call_tool(
        self,
        context: MiddlewareContext[CallToolRequestParams],
        call_next: CallNext[CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        site_id = _SiteArgument.model_validate(context.message.arguments or {}).site_id
        served = sorted(site.id for site in await sites.list_sites())
        if site_id not in served:
            msg = (
                f"site_id {site_id!r} is not a site this server serves. "
                f"Valid site_id values: {served}."
            )
            raise ToolError(msg)
        return await call_next(context)


@dataclass(frozen=True, slots=True)
class _ToolRow:
    """One served tool: what it does, what it claims, and what it declares."""

    fn: Callable[..., Any]
    annotations: ToolAnnotations
    meta: dict[str, Any] | None = None


TOOLS: tuple[_ToolRow, ...] = (
    _ToolRow(list_record_types, _READ),
    _ToolRow(search_for_searches, _READ),
    _ToolRow(browse_search_categories, _READ),
    _ToolRow(list_searches, _READ),
    _ToolRow(list_transforms, _READ),
    _ToolRow(lookup_phyletic_codes, _READ),
    _ToolRow(search_example_plans, _READ),
    _ToolRow(get_search_overview, _READ),
    _ToolRow(get_parameter_options, _READ),
    _ToolRow(lookup_gene_records, _READ),
    _ToolRow(get_ai_expression_summary, _READ),
    _ToolRow(resolve_gene_ids_to_records, _READ),
    _ToolRow(get_step_estimated_size, _READ),
    _ToolRow(get_step_sample_records, _READ),
    _ToolRow(get_step_download_url, _READ),
    _ToolRow(
        run_control_tests_on_search,
        _ADDITIVE_WRITE,
        {MAX_CALL_SECONDS_META_KEY: CONTROL_TESTS_MAX_CALL_SECONDS},
    ),
    _ToolRow(
        enrich_gene_ids,
        _ADDITIVE_WRITE,
        {
            STREAM_PART_META_KEY: {"kind": ENRICHMENT_PART_KIND, "version": 1},
            MAX_CALL_SECONDS_META_KEY: ENRICHMENT_MAX_CALL_SECONDS,
        },
    ),
)


def build_server() -> FastMCP[None]:
    """Build veupathdb-wdk-mcp with its seventeen tools and its per-call guards."""
    server: FastMCP[None] = FastMCP(
        name=SERVER_NAME,
        version=__version__,
        instructions=_INSTRUCTIONS,
        middleware=[WdkIdentity(), SiteGuard()],
    )
    for row in TOOLS:
        server.tool(row.fn, annotations=row.annotations, meta=row.meta)
    return server


__all__ = [
    "SERVER_NAME",
    "TOOLS",
    "SiteGuard",
    "WdkIdentity",
    "build_server",
]

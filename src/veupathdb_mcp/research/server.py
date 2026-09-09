"""veupathdb-research-mcp: literature and web search, served over MCP.

The server is stateless and names no VEuPathDB site. Every call reads the open
web on the deployment's own account, so it carries no user identity.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from veupathdb_mcp import __version__
from veupathdb_mcp.research.tools import literature_search, web_search
from veupathdb_mcp.tool_meta import (
    MAX_CALL_SECONDS_META_KEY,
    STREAM_PART_META_KEY,
)

SERVER_NAME = "veupathdb-research-mcp"

SOURCES_PART_KIND = "data-research.sources"

# Seven literature APIs answer in parallel, each retried past a rate limit.
RESEARCH_MAX_CALL_SECONDS = 60

_INSTRUCTIONS = (
    "Literature and web search. Both tools read the open web and name no "
    "VEuPathDB site. A result is ranked: the leading rows carry their text and "
    "the rest carry the url or the DOI that reaches it again."
)

# Both tools reach servers outside this deployment, which is what the open-world
# hint states. The WDK server closes it.
_OPEN_READ = ToolAnnotations(readOnlyHint=True, openWorldHint=True)

_DECLARED = {
    STREAM_PART_META_KEY: {"kind": SOURCES_PART_KIND, "version": 1},
    MAX_CALL_SECONDS_META_KEY: RESEARCH_MAX_CALL_SECONDS,
}


@dataclass(frozen=True, slots=True)
class _ToolRow:
    """One served tool: what it does, what it claims, and what it declares."""

    fn: Callable[..., Any]
    annotations: ToolAnnotations
    meta: dict[str, Any]


TOOLS: tuple[_ToolRow, ...] = (
    _ToolRow(web_search, _OPEN_READ, dict(_DECLARED)),
    _ToolRow(literature_search, _OPEN_READ, dict(_DECLARED)),
)


def build_server() -> FastMCP[None]:
    """Build veupathdb-research-mcp with its two tools."""
    server: FastMCP[None] = FastMCP(
        name=SERVER_NAME,
        version=__version__,
        instructions=_INSTRUCTIONS,
    )
    for row in TOOLS:
        server.tool(row.fn, annotations=row.annotations, meta=row.meta)
    return server


__all__ = [
    "RESEARCH_MAX_CALL_SECONDS",
    "SERVER_NAME",
    "SOURCES_PART_KIND",
    "TOOLS",
    "build_server",
]

"""Two MCP servers: veupathdb-wdk-mcp and veupathdb-research-mcp.

The root package holds what both servers share. The WDK credential path, its
settings and its published metadata stay on their own modules, beside the
server, the migration chain and the tool payloads: the research process
imports this package and carries neither a WDK account nor a database.
"""

from veupathdb_mcp.service_tokens import ServiceToken, ServiceTokenRegistry
from veupathdb_mcp.tool_errors import ToolErrorPayload, tool_error
from veupathdb_mcp.tool_meta import MAX_CALL_SECONDS_META_KEY, STREAM_PART_META_KEY

__version__ = "0.2.0a7"

__all__ = [
    "MAX_CALL_SECONDS_META_KEY",
    "STREAM_PART_META_KEY",
    "ServiceToken",
    "ServiceTokenRegistry",
    "ToolErrorPayload",
    "tool_error",
]

"""Two MCP servers: veupathdb-wdk-mcp and veupathdb-research-mcp.

The WDK server, its migration chain and its tool payloads stay on their own
modules: the research process imports this package and carries neither a WDK
catalog nor a database.
"""

from veupathdb_mcp.auth import (
    CredentialMode,
    McpCredential,
    VEuPathDBTokenVerifier,
    wdk_identity,
)
from veupathdb_mcp.metadata import DEFAULT_MCP_PATH, RESOURCE_NAME
from veupathdb_mcp.service_tokens import ServiceToken, ServiceTokenRegistry
from veupathdb_mcp.settings import (
    McpSettings,
    get_mcp_settings,
    use_mcp_settings_source,
)
from veupathdb_mcp.tool_errors import ToolErrorPayload, tool_error
from veupathdb_mcp.tool_meta import MAX_CALL_SECONDS_META_KEY, STREAM_PART_META_KEY

__version__ = "0.2.0a4"

__all__ = [
    "DEFAULT_MCP_PATH",
    "MAX_CALL_SECONDS_META_KEY",
    "RESOURCE_NAME",
    "STREAM_PART_META_KEY",
    "CredentialMode",
    "McpCredential",
    "McpSettings",
    "ServiceToken",
    "ServiceTokenRegistry",
    "ToolErrorPayload",
    "VEuPathDBTokenVerifier",
    "get_mcp_settings",
    "tool_error",
    "use_mcp_settings_source",
    "wdk_identity",
]

"""How a served tool turns a refusal into the tool error the caller reads."""

from __future__ import annotations

from fastmcp.exceptions import ToolError

from veupathdb_mcp.tool_errors import ToolErrorPayload


def payload_or_error[T](result: T | ToolErrorPayload) -> T:
    match result:
        case ToolErrorPayload():
            raise ToolError(result.message)
        case _:
            return result

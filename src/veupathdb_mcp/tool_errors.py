"""The typed payload a tool returns when it refuses."""

from enum import Enum

from pydantic import JsonValue
from veupathdb.json_types import JSONObject
from veupathdb.model import CamelModel


class ToolErrorPayload(CamelModel):
    """Complete tool-error wrapper validated at construction time."""

    ok: bool = False
    code: str
    message: str
    details: JSONObject | None = None


def tool_error(
    code: str | Enum, message: str, **details: JsonValue
) -> ToolErrorPayload:
    """Build a standardized tool error payload.

    :param code: Error code (string or Enum).
    :param message: Error message.
    :param details: Additional details as keyword arguments.
    :returns: Validated :class:`ToolErrorPayload` model.
    """
    code_value = code.value if isinstance(code, Enum) else str(code)
    details_obj: JSONObject | None = {**details} if details else None
    return ToolErrorPayload(
        code=code_value,
        message=message,
        details=details_obj,
    )

"""The wire vocabulary a consumer reads off a served tool's ``_meta``.

Both servers in this distribution state it. The runtime that reads it is a
separate distribution and is not imported here.
"""

from __future__ import annotations

STREAM_PART_META_KEY = "org.veupathdb.assistant/streamPart"
MAX_CALL_SECONDS_META_KEY = "org.veupathdb.assistant/maxCallSeconds"

__all__ = ["MAX_CALL_SECONDS_META_KEY", "STREAM_PART_META_KEY"]

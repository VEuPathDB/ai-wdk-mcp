"""The wire vocabulary a consumer reads off a served tool's ``_meta``.

Both servers in this distribution state it. The runtime that reads it is a
separate distribution and is not imported here.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

STREAM_PART_META_KEY = "org.veupathdb.assistant/streamPart"
MAX_CALL_SECONDS_META_KEY = "org.veupathdb.assistant/maxCallSeconds"
SHARE_FORMAT = "share"
Share = Annotated[float, Field(json_schema_extra={"format": SHARE_FORMAT})]
SENTENCE_FORMAT = "sentence"
Sentence = Annotated[str, Field(json_schema_extra={"format": SENTENCE_FORMAT})]

__all__ = [
    "MAX_CALL_SECONDS_META_KEY",
    "SENTENCE_FORMAT",
    "SHARE_FORMAT",
    "STREAM_PART_META_KEY",
    "Sentence",
    "Share",
]

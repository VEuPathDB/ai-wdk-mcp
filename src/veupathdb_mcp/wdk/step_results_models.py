"""The response model the sample read of a built step produces."""

from pydantic import Field
from veupathdb import JSONObject
from veupathdb.model import CamelModel


class SampleRecordsResult(CamelModel):
    """The first records of one built step, ready to render."""

    step_id: int
    total_count: int
    records: list[JSONObject] = Field(default_factory=list)
    attributes: list[str] = Field(default_factory=list)

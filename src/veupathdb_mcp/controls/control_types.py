"""What a control test takes, and what it returns."""

from dataclasses import dataclass, field
from typing import Literal

from pydantic import Field
from veupathdb.domain.parameters.values import ParamValue
from veupathdb.model import CamelModel

ControlValueFormat = Literal["newline", "json_list", "comma"]


class ControlTargetData(CamelModel):
    """Target step info in a control-test result."""

    search_name: str = ""
    parameters: dict[str, ParamValue] = Field(default_factory=dict)
    step_id: int | None = None
    estimated_size: int | None = None


class ControlSetData(CamelModel):
    """One control set (positive or negative) in a control-test result."""

    controls_count: int = 0
    intersection_count: int = 0
    intersection_ids: list[str] = Field(default_factory=list)
    intersection_ids_sample: list[str] = Field(default_factory=list)
    target_step_id: int | None = None
    target_estimated_size: int = 0
    missing_ids_sample: list[str] = Field(default_factory=list)
    unexpected_hits_sample: list[str] = Field(default_factory=list)
    recall: float | None = None
    false_positive_rate: float | None = None


class ControlTestResult(CamelModel):
    """Full control-test result (positive + negative intersection data)."""

    site_id: str = ""
    record_type: str = ""
    target: ControlTargetData = Field(default_factory=ControlTargetData)
    positive: ControlSetData | None = None
    negative: ControlSetData | None = None


@dataclass
class ControlsContext:
    """Site, record type, controls search config, and control gene lists."""

    site_id: str
    record_type: str
    controls_search_name: str
    controls_param_name: str
    controls_value_format: ControlValueFormat
    positive_controls: list[str] = field(default_factory=list)
    negative_controls: list[str] = field(default_factory=list)

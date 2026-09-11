"""What a control test takes, and what it returns."""

from dataclasses import dataclass, field
from typing import Literal

from pydantic import ConfigDict, Field
from veupathdb import JSONObject
from veupathdb.domain.parameters import ParamValue
from veupathdb.domain.strategy import DEFAULT_COMBINE_OPERATOR, CombineOp
from veupathdb.model import CamelModel

ControlValueFormat = Literal["newline", "json_list", "comma"]

DEFAULT_CONTROL_TEST_STRATEGY_NAME = "control test"


class ControlTargetData(CamelModel):
    """Target step info in a control-test result."""

    search_name: str = ""
    parameters: dict[str, ParamValue] = Field(default_factory=dict)
    step_id: int | None = None
    estimated_size: int | None = None


class ControlSetData(CamelModel):
    """One control set (positive or negative) in a control-test result.

    ``intersection_ids`` is None when the control set is over the limit one
    answer page reads, so the run reports a count and no identifiers.
    """

    controls_count: int = 0
    intersection_count: int = 0
    intersection_ids: list[str] | None = None
    intersection_ids_sample: list[str] = Field(default_factory=list)
    target_step_id: int | None = None
    target_estimated_size: int = 0
    missing_ids_sample: list[str] = Field(default_factory=list)
    unexpected_hits_sample: list[str] = Field(default_factory=list)
    recall: float | None = None
    false_positive_rate: float | None = None


class IntersectionSummary(CamelModel):
    """What one control-set intersection found: the count and the ids.

    ``intersection_ids`` is None when the control set is over the limit one
    answer page reads, so the run reports a count and no identifiers.
    """

    model_config = ConfigDict(extra="ignore", frozen=True, coerce_numbers_to_str=True)

    intersection_count: int = 0
    intersection_ids: list[str] | None = None

    @property
    def found_ids(self) -> set[str]:
        """The identifiers the intersection returned."""
        return set(self.intersection_ids or ())

    @property
    def ids_were_read(self) -> bool:
        """True when the run read identifiers, and not only a count."""
        return self.intersection_ids is not None


def summarize_intersection(payload: JSONObject) -> IntersectionSummary:
    """Read the count and the identifiers out of one intersection payload."""
    return IntersectionSummary.model_validate(payload)


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


@dataclass
class IntersectionConfig:
    """The target search and the controls search of one intersection run."""

    site_id: str
    record_type: str
    target_search_name: str
    target_parameters: dict[str, ParamValue]
    controls_search_name: str
    controls_param_name: str
    controls_value_format: ControlValueFormat = "newline"
    controls_extra_parameters: dict[str, ParamValue] | None = None
    boolean_operator: CombineOp = DEFAULT_COMBINE_OPERATOR
    id_field: str | None = None
    # The name of the internal strategy a run writes, and the name its cleanup
    # matches. One value, so a renamed run still recognises its own leftovers.
    internal_strategy_name: str = DEFAULT_CONTROL_TEST_STRATEGY_NAME

    @classmethod
    def from_controls_context(
        cls,
        ctx: ControlsContext,
        *,
        target_search_name: str,
        target_parameters: dict[str, ParamValue],
        controls_extra_parameters: dict[str, ParamValue] | None = None,
        id_field: str | None = None,
        internal_strategy_name: str = DEFAULT_CONTROL_TEST_STRATEGY_NAME,
    ) -> "IntersectionConfig":
        """Build an IntersectionConfig from a ControlsContext."""
        return cls(
            site_id=ctx.site_id,
            record_type=ctx.record_type,
            target_search_name=target_search_name,
            target_parameters=target_parameters,
            controls_search_name=ctx.controls_search_name,
            controls_param_name=ctx.controls_param_name,
            controls_value_format=ctx.controls_value_format,
            controls_extra_parameters=controls_extra_parameters,
            id_field=id_field,
            internal_strategy_name=internal_strategy_name,
        )

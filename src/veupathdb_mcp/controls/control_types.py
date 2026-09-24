"""What a control test takes, and what it returns."""

from collections import Counter
from collections.abc import Set
from dataclasses import dataclass, field
from typing import Literal, Self

from pydantic import ConfigDict, Field, model_validator
from veupathdb.domain.parameters import ParamValue
from veupathdb.domain.strategy import DEFAULT_COMBINE_OPERATOR, CombineOp
from veupathdb.model import CamelModel
from veupathdb.wdk import WDKStepTree

from veupathdb_mcp.computed import computed

ControlValueFormat = Literal["newline", "json_list", "comma"]

DEFAULT_CONTROL_TEST_STRATEGY_NAME = "control test"

CONTROLS_SEARCH = "GeneByLocusTag"
"""The transcript search that reads a gene id list."""
CONTROLS_PARAM = "ds_gene_ids"
"""The input-dataset parameter of ``CONTROLS_SEARCH``."""


class ControlTargetData(CamelModel):
    """Target step info in a control-test result."""

    search_name: str = ""
    parameters: dict[str, ParamValue] = Field(default_factory=dict)
    step_id: int | None = None
    estimated_size: int | None = None


def _partition_error(returned: list[str], not_returned: list[str]) -> str | None:
    """Why two id lists are not one control set, or None when they are."""
    if not returned and not not_returned:
        return "a control set holds at least one id"
    filed = Counter(returned + not_returned)
    repeated = sorted(gene_id for gene_id, times in filed.items() if times > 1)
    if repeated:
        return f"a control id is filed on one list only: {repeated}"
    return None


class PositiveControls(CamelModel):
    """The positive controls of one test, each filed as recovered or missed.

    The two lists partition the controls, so each count is read from them.
    """

    model_config = ConfigDict(frozen=True)

    recovered_ids: list[str]
    missed_ids: list[str]

    @classmethod
    def filed(cls, controls: list[str], returned: Set[str]) -> Self:
        """File each control by whether the target returned it."""
        ids = set(controls)
        return cls(
            recovered_ids=sorted(ids & returned), missed_ids=sorted(ids - returned)
        )

    @model_validator(mode="after")
    def _the_lists_partition_the_controls(self) -> Self:
        error = _partition_error(self.recovered_ids, self.missed_ids)
        if error is not None:
            raise ValueError(error)
        return self

    @computed
    def controls_count(self) -> int:
        """Every positive control the test was given."""
        return len(self.recovered_ids) + len(self.missed_ids)

    @computed
    def intersection_count(self) -> int:
        """The positive controls the target returned."""
        return len(self.recovered_ids)

    @computed
    def recall(self) -> float:
        """The share of the positive controls the target returned."""
        return self.intersection_count / self.controls_count


class NegativeControls(CamelModel):
    """The negative controls of one test, each filed as admitted or excluded.

    The two lists partition the controls, so each count is read from them.
    """

    model_config = ConfigDict(frozen=True)

    admitted_ids: list[str]
    excluded_ids: list[str]

    @classmethod
    def filed(cls, controls: list[str], returned: Set[str]) -> Self:
        """File each control by whether the target returned it."""
        ids = set(controls)
        return cls(
            admitted_ids=sorted(ids & returned), excluded_ids=sorted(ids - returned)
        )

    @model_validator(mode="after")
    def _the_lists_partition_the_controls(self) -> Self:
        error = _partition_error(self.admitted_ids, self.excluded_ids)
        if error is not None:
            raise ValueError(error)
        return self

    @computed
    def controls_count(self) -> int:
        """Every negative control the test was given."""
        return len(self.admitted_ids) + len(self.excluded_ids)

    @computed
    def intersection_count(self) -> int:
        """The negative controls the target returned."""
        return len(self.admitted_ids)

    @computed
    def false_positive_rate(self) -> float:
        """The share of the negative controls the target returned."""
        return self.intersection_count / self.controls_count


class ControlTestResult(CamelModel):
    """Full control-test result (positive + negative intersection data)."""

    site_id: str = ""
    record_type: str = ""
    target: ControlTargetData = Field(default_factory=ControlTargetData)
    positive: PositiveControls | None = None
    negative: NegativeControls | None = None


@dataclass(frozen=True)
class ControlsSearch:
    """The search that reads a control id list, and how its parameter takes the ids."""

    search_name: str = CONTROLS_SEARCH
    param_name: str = CONTROLS_PARAM
    record_type: str = "transcript"
    value_format: ControlValueFormat = "newline"
    extra_parameters: dict[str, ParamValue] = field(default_factory=dict)


@dataclass(frozen=True)
class ControlsDataset:
    """The controls, uploaded once, as the step spec every intersection of a run reads."""

    search_name: str
    parameters: dict[str, ParamValue]
    record_type: str


@dataclass(frozen=True)
class IntersectionTarget:
    """A step tree already on the account, and the record type its root returns."""

    tree: WDKStepTree
    record_type: str


@dataclass(frozen=True)
class Intersection:
    """The target's own count, and every control id the intersection returned."""

    target_count: int | None
    returned_ids: frozenset[str]


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

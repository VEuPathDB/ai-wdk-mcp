from collections.abc import Sequence
from typing import Literal, Self

from pydantic import ConfigDict, model_validator
from veupathdb.domain import WDKHistogramBin, WDKHistogramStatistics
from veupathdb.errors import DataParsingError, ValidationError
from veupathdb.model import CamelModel
from veupathdb.wdk import StrategyAPI, WDKAttributeField, WDKStep, get_strategy_api

DEFAULT_COLUMN_COUNT_TOP = 20
MAX_COLUMN_COUNT_TOP = 200

type ColumnDataType = Literal["STRING", "NUMBER", "DATE", "OTHER"]
type ColumnKind = Literal["string", "number"]

_BY_VALUE = "byValue"
_KINDS: dict[ColumnDataType, ColumnKind] = {"STRING": "string", "NUMBER": "number"}


class StepColumn(CamelModel):
    model_config = ConfigDict(frozen=True)

    name: str
    display_name: str
    data_type: ColumnDataType
    countable: bool


class StepColumns(CamelModel):
    model_config = ConfigDict(frozen=True)

    step_id: int
    record_type: str
    search_name: str
    columns: tuple[StepColumn, ...]

    def countable_names(self) -> tuple[str, ...]:
        return tuple(sorted(column.name for column in self.columns if column.countable))

    def named(self, name: str) -> StepColumn | None:
        return next((column for column in self.columns if column.name == name), None)


class CountedValue(CamelModel):
    model_config = ConfigDict(frozen=True)

    value: str
    count: int


class ColumnCounts(CamelModel):
    model_config = ConfigDict(frozen=True)

    step_id: int
    column: str
    display_name: str
    kind: ColumnKind
    total_records: int
    distinct_values: int
    values: tuple[CountedValue, ...] = ()
    bins: tuple[WDKHistogramBin, ...] = ()
    statistics: WDKHistogramStatistics | None = None

    @model_validator(mode="after")
    def _one_shape_per_kind(self) -> Self:
        if self.kind == "string" and (self.bins or self.statistics is not None):
            msg = "a string column answers ranked values, not bins"
            raise ValueError(msg)
        if self.kind == "number" and (self.values or self.statistics is None):
            msg = "a number column answers its bins and statistics"
            raise ValueError(msg)
        return self


class ColumnNotCountedError(ValidationError):
    def __init__(
        self,
        step_id: int,
        column: str,
        data_type: ColumnDataType | None,
        countable: tuple[str, ...],
    ) -> None:
        self.step_id = step_id
        self.column = column
        self.data_type = data_type
        self.countable = countable
        reason = (
            f"{column!r} is not a column of step {step_id}"
            if data_type is None
            else (
                f"column {column!r} of step {step_id} is {data_type} and has no "
                "byValue count on this site"
            )
        )
        super().__init__(
            title="Column cannot be counted",
            detail=f"{reason}. Columns that can be counted: {', '.join(countable)}",
        )


def _countable(field: WDKAttributeField) -> bool:
    return field.column_data_type in _KINDS and _BY_VALUE in field.tools.reports


def _column(field: WDKAttributeField) -> StepColumn:
    return StepColumn(
        name=field.name,
        display_name=field.display_name or field.name,
        data_type=field.column_data_type,
        countable=_countable(field),
    )


def _merged(*fields: Sequence[WDKAttributeField]) -> tuple[StepColumn, ...]:
    by_name = {field.name: _column(field) for group in fields for field in group}
    return tuple(by_name.values())


async def _step_columns(api: StrategyAPI, step: WDKStep) -> StepColumns:
    if not step.record_class_name:
        msg = f"step {step.id} names no record type"
        raise DataParsingError(msg)
    record_type = await api.get_record_type_info(step.record_class_name)
    search = await api.client.get_search_details(
        step.record_class_name, step.search_name, expand_params=False
    )
    return StepColumns(
        step_id=step.id,
        record_type=step.record_class_name,
        search_name=step.search_name,
        columns=_merged(
            record_type.attributes or [],
            list((record_type.attributes_map or {}).values()),
            search.search_data.dynamic_attributes,
        ),
    )


async def list_step_columns(site_id: str, step_id: int) -> StepColumns:
    api = get_strategy_api(site_id)
    return await _step_columns(api, await api.find_step(step_id))


def _require_top(top: int) -> None:
    if not 1 <= top <= MAX_COLUMN_COUNT_TOP:
        msg = f"top must be from 1 to {MAX_COLUMN_COUNT_TOP}, not {top}"
        raise ValueError(msg)


def _ranked(bins: Sequence[WDKHistogramBin], top: int) -> tuple[CountedValue, ...]:
    ranked = sorted(bins, key=lambda bin_: -bin_.value)
    return tuple(
        CountedValue(value=bin_.bin_label, count=bin_.value) for bin_ in ranked[:top]
    )


async def count_by_column(
    site_id: str,
    step_id: int,
    column: str,
    top: int = DEFAULT_COLUMN_COUNT_TOP,
    *,
    budget_seconds: float | None = None,
) -> ColumnCounts:
    _require_top(top)
    api = get_strategy_api(site_id)
    listed = await _step_columns(api, await api.find_step(step_id))
    found = listed.named(column)
    if found is None or not found.countable:
        raise ColumnNotCountedError(
            step_id,
            column,
            None if found is None else found.data_type,
            listed.countable_names(),
        )
    kind = _KINDS[found.data_type]
    distribution = await api.get_column_distribution(
        step_id, column, budget_seconds=budget_seconds
    )
    statistics = distribution.statistics
    return ColumnCounts(
        step_id=step_id,
        column=column,
        display_name=found.display_name,
        kind=kind,
        total_records=statistics.subset_size,
        distinct_values=statistics.num_distinct_values,
        values=_ranked(distribution.histogram, top) if kind == "string" else (),
        bins=tuple(distribution.histogram) if kind == "number" else (),
        statistics=statistics if kind == "number" else None,
    )

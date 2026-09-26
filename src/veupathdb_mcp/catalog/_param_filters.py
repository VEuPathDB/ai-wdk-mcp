"""Resolution of a WDK filter parameter against its ontology facets."""

from __future__ import annotations

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, RootModel, model_validator
from pydantic import ValidationError as PydanticValidationError
from veupathdb.domain.parameters import (
    FilterTermClause,
    FilterValue,
    UnboundParameter,
    VocabOption,
)
from veupathdb.errors import ValidationError
from veupathdb.model import CamelModel

from veupathdb_mcp.catalog._param_binding import _MAX_SLOT_OPTIONS, OverrideMap
from veupathdb_mcp.catalog.param_formatting import (
    FilterFieldInfo,
    ParameterInfo,
)
from veupathdb_mcp.catalog.param_intent import match_option


def _match_filter_field(info: ParameterInfo, hint: str) -> FilterFieldInfo | None:
    """Resolves a facet by name. An exact term or display match wins over a substring."""
    hint_l = hint.strip().lower()
    for field in info.filter_fields:
        if hint_l in (field.term.lower(), field.display.lower()):
            return field
    return next(
        (
            field
            for field in info.filter_fields
            if hint_l in field.term.lower() or hint_l in field.display.lower()
        ),
        None,
    )


def _match_filter_values(
    field: FilterFieldInfo, raw_values: list[str]
) -> list[JsonValue]:
    """Matches each requested member against the facet's values. An unknown member
    passes through for WDK to validate."""
    options = [VocabOption(value=v, display=v) for v in field.values]
    return [match_option(options, v) or v for v in raw_values]


def _is_range(field: FilterFieldInfo) -> bool:
    """WDK parses a date clause as a range whatever its isRange flag says."""
    return field.is_range or field.type == "date"


class _Bounds(BaseModel):
    """The bounds of a range clause. WDK reads an absent bound as unbounded."""

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def _one_bound(self) -> Self:
        if not self.model_dump(exclude_none=True):
            msg = "a range states min, max or both"
            raise ValueError(msg)
        return self


class _NumberBounds(_Bounds):
    min: float | None = None
    max: float | None = None


class _DateBounds(_Bounds):
    min: str | None = None
    max: str | None = None


class _Members(RootModel[list[str]]):
    """The members a clause selects. One member may be written without a list."""

    model_config = ConfigDict(coerce_numbers_to_str=True)

    @model_validator(mode="before")
    @classmethod
    def _one_or_many(cls, raw: JsonValue) -> JsonValue:
        if raw is None:
            return []
        return raw if isinstance(raw, list) else [raw]


def _range_forms(term: str) -> str:
    return (
        f"'{term}<=<n>', '{term}>=<n>' or '{term}=<lo>..<hi>', or the JSON value "
        '{"min": <n>, "max": <n>} with either bound left out'
    )


def _member_forms(term: str) -> str:
    return f'\'{term}=<m1>,<m2>\' or the JSON value ["<m1>", "<m2>"]'


def _refused(
    info: ParameterInfo, field: FilterFieldInfo, value: JsonValue
) -> ValidationError:
    kind, forms = (
        ("range", _range_forms(field.term))
        if _is_range(field)
        else ("member", _member_forms(field.term))
    )
    return ValidationError(
        title="Invalid parameter value",
        detail=f"Facet '{field.term}' of '{info.name}' is a {kind} facet. Write {forms}.",
        errors=[{"param": info.name, "facet": field.term, "value": value}],
    )


def _clause(
    info: ParameterInfo, field: FilterFieldInfo, value: JsonValue
) -> FilterTermClause:
    """Writes a clause's value in the shape WDK parses for its facet."""
    try:
        if _is_range(field):
            bounds = _DateBounds if field.type == "date" else _NumberBounds
            written: JsonValue = bounds.model_validate(value).model_dump(
                exclude_none=True
            )
        else:
            written = _match_filter_values(field, _Members.model_validate(value).root)
    except PydanticValidationError as exc:
        raise _refused(info, field, value) from exc
    return FilterTermClause(
        field=field.term, type=field.type, is_range=field.is_range, value=written
    )


class _RawFilterClause(CamelModel):
    """A clause as the model emits it, which may be partial. The type, isRange and
    includeUnknown fields come from the ontology instead."""

    model_config = ConfigDict(extra="ignore")
    field: str = ""
    value: JsonValue = Field(default_factory=list)


class _RawFilterInput(CamelModel):
    """The WDK filters wrapper. Clauses may be partial and bind to the ontology later."""

    model_config = ConfigDict(extra="ignore")
    filters: list[_RawFilterClause]


def _enrich_clause(
    info: ParameterInfo, raw: _RawFilterClause
) -> FilterTermClause | None:
    """Binds a clause to an ontology facet and writes its value for that facet.
    A clause for an unknown facet passes through for WDK to validate."""
    if not raw.field:
        return None
    facet = _match_filter_field(info, raw.field)
    if facet is None:
        return FilterTermClause(field=raw.field, value=raw.value)
    return _clause(info, facet, raw.value)


def _filter_from_json(info: ParameterInfo, text: str) -> FilterValue:
    try:
        parsed = _RawFilterInput.model_validate_json(text)
    except PydanticValidationError as exc:
        raise ValidationError(
            title="Invalid parameter value",
            detail=(
                f"Parameter '{info.name}' takes filter JSON "
                '{"filters": [{"field": "<facet>", "value": <value>}]} '
                "or the shorthand '<facet>=<value>'."
            ),
            errors=[{"param": info.name, "value": text}],
        ) from exc
    clauses = [
        clause
        for raw in parsed.filters
        if (clause := _enrich_clause(info, raw)) is not None
    ]
    return FilterValue(filters=clauses)


_CONTRAST_PREFIXES: tuple[tuple[str, str], ...] = (("ref", "comp"), ("comp", "ref"))


def has_contrast_sibling(info: ParameterInfo, infos: list[ParameterInfo]) -> bool:
    """Reports whether this filter param is one half of a reference and comparison
    sample pair. Both halves taking the empty all-samples filter is a degenerate
    contrast, so the pair is surfaced instead of auto-resolved."""
    name = info.name
    for this, other in _CONTRAST_PREFIXES:
        prefix = f"{this}_"
        if name.startswith(prefix):
            sibling = f"{other}_{name[len(prefix) :]}"
            return any(i.name == sibling and i.param_kind == "filter" for i in infos)
    return False


def _contrast_open_slot(info: ParameterInfo) -> UnboundParameter:
    return UnboundParameter(
        param_name=info.name,
        question=(
            f"Choose the sample group for {info.display_name}: a "
            f"reference-vs-comparison contrast needs DISTINCT groups on each "
            f"side, not all samples on both."
        ),
        options=[
            f"{field.term}={value}"
            for field in info.filter_fields
            for value in field.values
        ][:_MAX_SLOT_OPTIONS],
    )


def _resolve_filter_param(
    info: ParameterInfo, infos: list[ParameterInfo], overrides: OverrideMap
) -> FilterValue | UnboundParameter:
    """Resolves a filter param to a value, or returns an UnboundParameter for an
    unspecified half of a contrast pair."""
    override = overrides.get(info.name)
    if isinstance(override, list):
        raise ValidationError(
            title="Invalid parameter value",
            detail=(
                f"Parameter '{info.name}' is a filter, and each clause names ONE "
                f"facet. A bare list names no facet. Pass a member facet as "
                f"'<facet>=<m1>,<m2>' and a range facet as '<facet><=<n>', "
                f"'<facet>>=<n>' or '<facet>=<lo>..<hi>'."
            ),
            errors=[{"param": info.name, "value": list(override)}],
        )
    if override is None and has_contrast_sibling(info, infos):
        return _contrast_open_slot(info)
    return _resolve_filter(info, override)


def _shorthand_value(
    info: ParameterInfo, field: FilterFieldInfo, bound: str, raw: str
) -> JsonValue:
    """Reads the value of the shorthand: members for a member facet, and
    <=x, >=x or =lo..hi for a range facet."""
    if not _is_range(field):
        if bound:
            raise _refused(info, field, raw)
        return [v.strip() for v in raw.split(",") if v.strip()]
    if bound == "<":
        return {"max": raw}
    if bound == ">":
        return {"min": raw}
    low, dots, high = raw.partition("..")
    return {"min": low.strip() or None, "max": high.strip() or None} if dots else raw


def _resolve_filter(info: ParameterInfo, override: str | None) -> FilterValue:
    """Builds a filter param value. The WDK default is the empty filter set, which
    includes all samples. An override is either WDK filter JSON or the shorthand
    on one ontology facet: facet=value1,value2 for a member facet, and
    facet<=x, facet>=x or facet=lo..hi for a range facet."""
    if not override:
        return FilterValue()
    text = override.strip()
    if text.startswith("{"):
        return _filter_from_json(info, text)
    field_hint, sep, raw = text.partition("=")
    bound = field_hint[-1] if field_hint.endswith(("<", ">")) else ""
    field = _match_filter_field(info, field_hint.removesuffix(bound)) if sep else None
    value = _shorthand_value(info, field, bound, raw.strip()) if field else None
    if field is None or not value:
        return FilterValue()
    return FilterValue(filters=[_clause(info, field, value)])

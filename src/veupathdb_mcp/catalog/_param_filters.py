"""Resolution of a WDK filter parameter against its ontology facets."""

from __future__ import annotations

from pydantic import ConfigDict, Field, JsonValue, field_validator
from pydantic import ValidationError as PydanticValidationError
from veupathdb.domain.parameters.values import FilterTermClause, FilterValue
from veupathdb.domain.parameters.wdk_vocab import VocabOption
from veupathdb.domain.strategy.operational_spec import OpenSlot
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


class _RawFilterClause(CamelModel):
    """A clause as the model emits it, which may be partial. The type, isRange and
    includeUnknown fields come from the ontology instead."""

    model_config = ConfigDict(extra="ignore")
    field: str = ""
    value: list[JsonValue] = Field(default_factory=list)

    @field_validator("value", mode="before")
    @classmethod
    def _as_member_list(cls, v: JsonValue) -> JsonValue:
        if v is None:
            return []
        return v if isinstance(v, list) else [v]


class _RawFilterInput(CamelModel):
    """The WDK filters wrapper. Clauses may be partial and bind to the ontology later."""

    model_config = ConfigDict(extra="ignore")
    filters: list[_RawFilterClause] = Field(default_factory=list)


def _enrich_clause(
    info: ParameterInfo, raw: _RawFilterClause
) -> FilterTermClause | None:
    """Binds a clause to an ontology facet and matches its members to the facet values.
    A clause for an unknown facet passes through for WDK to validate."""
    if not raw.field:
        return None
    facet = _match_filter_field(info, raw.field)
    if facet is None:
        return FilterTermClause(field=raw.field, value=raw.value)
    return FilterTermClause(
        field=facet.term,
        type=facet.type,
        is_range=facet.is_range,
        value=_match_filter_values(facet, [str(v) for v in raw.value]),
    )


def _filter_from_json(info: ParameterInfo, text: str) -> FilterValue:
    try:
        parsed = _RawFilterInput.model_validate_json(text)
    except PydanticValidationError:
        return FilterValue()
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


def _contrast_open_slot(info: ParameterInfo) -> OpenSlot:
    return OpenSlot(
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
) -> FilterValue | OpenSlot:
    """Resolves a filter param to a value, or returns an OpenSlot for an unspecified
    half of a contrast pair."""
    override = overrides.get(info.name)
    if isinstance(override, list):
        raise ValidationError(
            title="Invalid parameter value",
            detail=(
                f"Parameter '{info.name}' is a filter, which selects members of "
                f"ONE facet. A bare list names no facet. Pass "
                f"'<facet>=<value1>,<value2>' instead, e.g. "
                f"'{info.filter_fields[0].term if info.filter_fields else 'Sample type'}"
                f"={','.join(override[:2])}'."
            ),
            errors=[{"param": info.name, "value": list(override)}],
        )
    if override is None and has_contrast_sibling(info, infos):
        return _contrast_open_slot(info)
    return _resolve_filter(info, override)


def _resolve_filter(info: ParameterInfo, override: str | None) -> FilterValue:
    """Builds a filter param value. The WDK default is the empty filter set, which
    includes all samples. An override is either WDK filter JSON or the shorthand
    facet=value1,value2, and both select members of one ontology facet."""
    if not override:
        return FilterValue()
    text = override.strip()
    if text.startswith("{"):
        return _filter_from_json(info, text)
    field_hint, sep, raw = text.partition("=")
    if not sep:
        return FilterValue()
    field = _match_filter_field(info, field_hint)
    if field is None:
        return FilterValue()
    raw_values = [v.strip() for v in raw.split(",") if v.strip()]
    if not raw_values:
        return FilterValue()
    return FilterValue(
        filters=[
            FilterTermClause(
                field=field.term,
                type=field.type,
                is_range=field.is_range,
                value=_match_filter_values(field, raw_values),
            )
        ]
    )

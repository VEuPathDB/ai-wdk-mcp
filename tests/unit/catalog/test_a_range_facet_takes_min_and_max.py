"""A filter clause's value takes the shape WDK parses for its facet: an object
with bounds for a range facet, a member list for a member facet."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from veupathdb.devtools.wdk_capture import WDKExchange
from veupathdb.domain.parameters import FilterValue
from veupathdb.errors import ValidationError
from veupathdb.wdk import WDKSearchResponse

from veupathdb_mcp.catalog.param_dag import ParameterInfo, resolve_params_with_intent
from veupathdb_mcp.catalog.param_formatting import (
    FilterFieldInfo,
    format_typed_param,
)
from veupathdb_mcp.catalog.param_intent import ParamIntent

from .conftest import fetcher, param_info

_RECORDED = (
    Path(__file__).parent / "fixtures" / "plasmodb_variant_characteristics_refresh.json"
)
_PARAM = "gene_variant_stats"


def _variant_stats() -> ParameterInfo:
    exchange = WDKExchange.model_validate_json(_RECORDED.read_text())
    search = WDKSearchResponse.model_validate(exchange.response_json).search_data
    param = next(p for p in search.parameters or [] if p.name == _PARAM)
    return format_typed_param(param, {}, {})


def _collection_dates() -> ParameterInfo:
    return param_info(
        "sample_meta",
        "filter",
        filter_fields=[
            FilterFieldInfo(
                term="collection_date",
                display="Collection date",
                type="date",
                is_range=True,
            )
        ],
    )


async def _wire(info: ParameterInfo, override: str) -> list[dict[str, object]]:
    resolved = await resolve_params_with_intent(
        fetch_at=fetcher(info),
        intent=ParamIntent(),
        overrides={info.name: override},
    )
    value = resolved.params[info.name]
    assert isinstance(value, FilterValue)
    wire = json.loads(value.to_wire())
    assert isinstance(wire, dict)
    clauses: list[dict[str, object]] = wire["filters"]
    return clauses


@pytest.mark.parametrize(
    ("override", "bounds"),
    [
        ("max_minor_allele_frequency<=0.05", {"max": 0.05}),
        ("max_minor_allele_frequency>=0.01", {"min": 0.01}),
        ("variants_per_kb=0..0", {"min": 0.0, "max": 0.0}),
        ("Variants per kb=..2.5", {"max": 2.5}),
        (
            (
                '{"filters": [{"field": "max_minor_allele_frequency", '
                '"value": {"max": 0.05}}]}'
            ),
            {"max": 0.05},
        ),
        (
            (
                '{"filters": [{"field": "variants_per_kb", "type": "number", '
                '"isRange": true, "includeUnknown": false, '
                '"value": {"min": 0, "max": 0}}]}'
            ),
            {"min": 0.0, "max": 0.0},
        ),
    ],
)
async def test_a_range_facet_is_written_as_min_and_max(
    override: str, bounds: dict[str, float]
) -> None:
    [clause] = await _wire(_variant_stats(), override)

    assert clause["type"] == "number"
    assert clause["isRange"] is True
    assert clause["value"] == bounds


@pytest.mark.parametrize(
    "override",
    [
        "most_severe_impact=HIGH",
        '{"filters": [{"field": "most_severe_impact", "value": ["HIGH"]}]}',
        '{"filters": [{"field": "most_severe_impact", "value": "HIGH"}]}',
    ],
)
async def test_a_member_facet_is_written_as_a_member_list(override: str) -> None:
    [clause] = await _wire(_variant_stats(), override)

    assert clause["field"] == "most_severe_impact"
    assert clause["isRange"] is False
    assert clause["value"] == ["HIGH"]


async def test_a_date_facet_is_written_as_min_and_max() -> None:
    [clause] = await _wire(
        _collection_dates(), "collection_date=2019-01-01..2020-12-31"
    )

    assert clause["type"] == "date"
    assert clause["value"] == {"min": "2019-01-01", "max": "2020-12-31"}


@pytest.mark.parametrize(
    "override",
    [
        "variants_per_kb=0",
        "variants_per_kb<=a lot",
        "variants_per_kb=..",
        '{"filters": [{"field": "variants_per_kb", "value": ["0"]}]}',
        '{"filters": [{"field": "variants_per_kb", "value": {"max": 1, "gt": 0}}]}',
    ],
)
async def test_a_range_facet_refuses_a_member_value_naming_both_forms(
    override: str,
) -> None:
    with pytest.raises(ValidationError) as caught:
        await _wire(_variant_stats(), override)

    detail = caught.value.detail
    assert "variants_per_kb<=<n>" in detail
    assert '{"min": <n>, "max": <n>}' in detail


async def test_a_member_facet_refuses_bounds_naming_both_forms() -> None:
    override = '{"filters": [{"field": "most_severe_impact", "value": {"max": 1}}]}'

    with pytest.raises(ValidationError) as caught:
        await _wire(_variant_stats(), override)

    detail = caught.value.detail
    assert "most_severe_impact=<m1>,<m2>" in detail
    assert '["<m1>", "<m2>"]' in detail


async def test_filter_json_without_a_clause_list_is_refused() -> None:
    with pytest.raises(ValidationError, match="filters"):
        await _wire(_variant_stats(), '{"max_minor_allele_frequency": {"max": 0.05}}')


async def test_a_bare_list_is_refused_naming_both_facet_forms() -> None:
    info = _variant_stats()

    with pytest.raises(ValidationError) as caught:
        await resolve_params_with_intent(
            fetch_at=fetcher(info),
            intent=ParamIntent(),
            overrides={info.name: ["0", "1"]},
        )

    detail = caught.value.detail
    assert "'<facet>=<m1>,<m2>'" in detail
    assert "'<facet>=<lo>..<hi>'" in detail


def test_the_sheet_states_the_member_and_the_range_form() -> None:
    value_format = _variant_stats().value_format

    assert '"value": ["<member>", "..."]' in value_format
    assert '"value": {"min": <n>, "max": <n>}' in value_format
    assert "<range facet><=<n>" in value_format
    assert "<range facet>=<lo>..<hi>" in value_format
    assert "<member facet>=<m1>,<m2>" in value_format

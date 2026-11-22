"""A filter clause's value takes the shape WDK parses for its facet: an object
with bounds for a range facet, a member list for a member facet."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest
from pydantic import JsonValue
from tests._support.filter_reads import FilterReadsDouble
from tests._support.recordings import TEST_ROOT
from veupathdb.devtools import WDKExchange
from veupathdb.domain.parameters import FilterValue, ParamGraph
from veupathdb.errors import ValidationError
from veupathdb.testing import NEEDS_QA_RECORDING, needs_qa_recording
from veupathdb.wdk import WDKSearchResponse

from veupathdb_mcp.catalog.param_dag import ParameterInfo, resolve_params_with_intent
from veupathdb_mcp.catalog.param_formatting import format_typed_param
from veupathdb_mcp.catalog.param_intent import ParamIntent

from .conftest import facet, fetcher, param_info

_RECORDED = (
    Path(__file__).parent / "fixtures" / "plasmodb_variant_characteristics_refresh.json"
)
_PARAM = "gene_variant_stats"


def _variant_stats() -> ParameterInfo:
    exchange = WDKExchange.model_validate_json(_RECORDED.read_text())
    search = WDKSearchResponse.model_validate(exchange.response_json).search_data
    param = next(p for p in search.parameters or [] if p.name == _PARAM)
    return format_typed_param(param, ParamGraph.of([param]))


def _collection_dates() -> ParameterInfo:
    return param_info(
        "sample_meta",
        "filter",
        filter_fields=[
            facet("collection_date", "date", display="Collection date", is_range=True)
        ],
    )


async def _wire(info: ParameterInfo, statement: object) -> list[dict[str, object]]:
    resolved = await resolve_params_with_intent(
        filter_reads=FilterReadsDouble(),
        fetch_at=fetcher(info),
        search_name="GenesByFacet",
        intent=ParamIntent(),
        stated={info.name: cast("JsonValue", statement)},
        about=None,
    )
    value = resolved.params[info.name]
    assert isinstance(value, FilterValue)
    wire = json.loads(value.to_wire())
    assert isinstance(wire, dict)
    clauses: list[dict[str, object]] = wire["filters"]
    return clauses


_NEEDS_REFRESH = pytest.mark.skipif(
    needs_qa_recording(
        TEST_ROOT
        / "unit/catalog/fixtures/plasmodb_variant_characteristics_refresh.json"
    ),
    reason=NEEDS_QA_RECORDING,
)


@_NEEDS_REFRESH
@pytest.mark.parametrize(
    ("statement", "bounds"),
    [
        (
            [{"field": "max_minor_allele_frequency", "value": {"max": 0.05}}],
            {"max": 0.05},
        ),
        (
            [{"field": "max_minor_allele_frequency", "value": {"min": 0.01}}],
            {"min": 0.01},
        ),
        (
            [{"field": "variants_per_kb", "value": {"min": 0, "max": 0}}],
            {"min": 0.0, "max": 0.0},
        ),
        ([{"field": "Variants per kb", "value": {"max": 2.5}}], {"max": 2.5}),
    ],
)
async def test_a_range_facet_is_written_as_min_and_max(
    statement: object, bounds: dict[str, float]
) -> None:
    [clause] = await _wire(_variant_stats(), statement)

    assert clause["type"] == "number"
    assert clause["isRange"] is True
    assert clause["value"] == bounds


@_NEEDS_REFRESH
async def test_a_member_facet_is_written_as_a_member_list() -> None:
    [clause] = await _wire(
        _variant_stats(), [{"field": "most_severe_impact", "value": ["HIGH"]}]
    )

    assert clause["field"] == "most_severe_impact"
    assert clause["isRange"] is False
    assert clause["value"] == ["HIGH"]


async def test_a_date_facet_is_written_as_min_and_max() -> None:
    [clause] = await _wire(
        _collection_dates(),
        [
            {
                "field": "collection_date",
                "value": {"min": "2019-01-01", "max": "2020-12-31"},
            }
        ],
    )

    assert clause["type"] == "date"
    assert clause["value"] == {"min": "2019-01-01", "max": "2020-12-31"}


@_NEEDS_REFRESH
@pytest.mark.parametrize(
    "value",
    [["0"], {"max": 1, "gt": 0}, {}],
)
async def test_a_range_facet_refuses_a_value_that_is_not_its_bounds(
    value: object,
) -> None:
    with pytest.raises(ValidationError) as caught:
        await _wire(_variant_stats(), [{"field": "variants_per_kb", "value": value}])

    assert '"value": {"min": <n>, "max": <n>}' in caught.value.detail


@_NEEDS_REFRESH
async def test_a_member_facet_refuses_bounds_naming_its_member_form() -> None:
    with pytest.raises(ValidationError) as caught:
        await _wire(
            _variant_stats(), [{"field": "most_severe_impact", "value": {"max": 1}}]
        )

    assert '"value": ["<member>", ...]' in caught.value.detail


@_NEEDS_REFRESH
@pytest.mark.parametrize(
    "statement",
    [
        {"max_minor_allele_frequency": {"max": 0.05}},
        ["0", "1"],
        "most_severe_impact=HIGH",
        [{"field": "most_severe_impact", "value": "HIGH"}],
        [],
    ],
)
async def test_a_statement_that_is_not_a_clause_list_is_refused(
    statement: object,
) -> None:
    with pytest.raises(ValidationError) as caught:
        await _wire(_variant_stats(), statement)

    assert "gene_variant_stats" in caught.value.detail


@pytest.mark.skipif(
    needs_qa_recording(
        TEST_ROOT
        / "unit/catalog/fixtures/plasmodb_variant_characteristics_refresh.json"
    ),
    reason=NEEDS_QA_RECORDING,
)
def test_the_schema_states_a_member_list_or_a_range_per_facet() -> None:
    schema = _variant_stats().stated_schema

    assert schema["type"] == "array"
    clause = cast("dict[str, Any]", schema["items"])["properties"]
    assert "total_variants" in clause["field"]["enum"]
    assert [form["type"] for form in clause["value"]["anyOf"]] == ["array", "object"]
    assert "valueFormat" not in _variant_stats().model_dump(by_alias=True)

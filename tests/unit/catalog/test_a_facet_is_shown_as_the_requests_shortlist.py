"""A filter facet keeps every value the site sent, and a model reads each facet
whole up to the sheet limit and as the request's shortlist past it."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from veupathdb.testing.wdk_fixtures import load_recorded
from veupathdb.wdk import WDKSearchResponse

from veupathdb_mcp.catalog import (
    ParameterInfo,
    VocabNarrowing,
    build_sheet,
    format_param_info_typed,
    read_parameter_options,
    search_inspection,
)
from veupathdb_mcp.catalog.shortlist import TOP_K

_COUNTRY = "VAR_8e68b3e5"
_SAMPLE_NAME = "VAR_41eb2167"


def _samples() -> ParameterInfo:
    body = load_recorded("search_genes_by_ngs_snps").json_body()
    infos = format_param_info_typed(
        WDKSearchResponse.model_validate(body).search_data.parameters or []
    )
    return next(info for info in infos if info.name == "variation_sample_meta")


def _values(facets: list[dict[str, object]], term: str) -> object:
    return next(facet["values"] for facet in facets if facet["term"] == term)


def _total(facets: list[dict[str, object]], term: str) -> object:
    return next(facet["valuesTotal"] for facet in facets if facet["term"] == term)


def test_every_facet_value_is_kept() -> None:
    whole = {field.term: field.values for field in _samples().facets()}

    assert sum(len(values) for values in whole.values()) == 1521
    assert "Gambia" in whole[_COUNTRY]
    assert len(whole[_SAMPLE_NAME]) == 537


def test_a_read_shows_a_short_facet_whole_and_a_long_one_cut() -> None:
    shown = _samples().model_dump(by_alias=True, mode="json")["filterFields"]

    assert "Gambia" in _values(shown, _COUNTRY)
    assert len(_values(shown, _COUNTRY)) == 20
    assert len(_values(shown, _SAMPLE_NAME)) == TOP_K
    assert _total(shown, _SAMPLE_NAME) == 537
    assert _total(shown, _COUNTRY) is None


def test_the_sheet_shows_a_long_facet_as_the_requests_shortlist() -> None:
    [entry] = build_sheet([_samples()], query="isolate UGK_661.1 against Gambia")

    facets = {field.term: field.values for field in entry.filter_facets}
    assert facets[_SAMPLE_NAME][0] == "UGK_661.1"
    assert len(facets[_SAMPLE_NAME]) == TOP_K
    assert "Gambia" in facets[_COUNTRY]
    assert "Sample name" in (entry.vocabulary_note or "")
    assert "get_parameter_options" in (entry.vocabulary_note or "")


async def test_a_read_with_a_query_shows_the_facet_values_it_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = WDKSearchResponse.model_validate(
        load_recorded("search_genes_by_ngs_snps").json_body()
    )
    client = MagicMock()
    client.get_search_details = AsyncMock(return_value=response)
    client.get_search_details_with_params = AsyncMock(return_value=response)
    monkeypatch.setattr(search_inspection, "get_wdk_client", lambda _site: client)

    read = await read_parameter_options(
        "plasmodb",
        "GenesByNgsSnps",
        "variation_sample_meta",
        record_type="transcript",
        context_values={
            "organismSinglePick": "Plasmodium falciparum 3D7",
            "eda_sample_table_suffix": "s3be28bbe14_sample",
        },
        narrowing=VocabNarrowing(query="UGK_661.1"),
    )

    assert isinstance(read, ParameterInfo)
    shown = {field.term: field.values for field in read.filter_fields}
    assert shown[_SAMPLE_NAME][0] == "UGK_661.1"

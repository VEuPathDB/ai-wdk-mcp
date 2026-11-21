"""A stated filter is refused when its range selects nothing, or when it selects
fewer records than the parameter's minimum, as the VEuPathDB website refuses it."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from tests._support.filter_reads import FilterReadsDouble
from tests._support.wdk_reads import serve_reads
from veupathdb.devtools import WDKExchange
from veupathdb.domain.parameters import (
    FilterFacet,
    FilterFacets,
    FilterValue,
    MultiPickValue,
    StringMembers,
)
from veupathdb.testing import NEEDS_QA_RECORDING, needs_qa_recording
from veupathdb.testing.wdk_fixtures import load_recorded
from veupathdb.wdk import (
    WDKFilterParam,
    WDKFilterSummaryCounts,
    WDKOntologyTermSummary,
    WDKParameter,
    WDKSearchResponse,
)

from veupathdb_mcp.catalog import (
    ParameterInfo,
    VocabNarrowing,
    facet_ranges,
    read_parameter_options,
    search_inspection,
    searches,
)
from veupathdb_mcp.catalog.discovery import CatalogPolicy, SearchCatalog
from veupathdb_mcp.catalog.facet_ranges import (
    EmptyRangeError,
    TooFewSelectedError,
    WDKFilterReads,
)
from veupathdb_mcp.catalog.param_dag import resolve_params_with_intent
from veupathdb_mcp.catalog.param_intent import ParamIntent

from .conftest import serving
from .test_a_filter_statement_binds_by_its_facet import (
    ngs_snps,
    variant_characteristics,
)

_PF = ["Plasmodium falciparum 3D7"]
_SAMPLE_CONTEXT = {
    "organismSinglePick": '["Plasmodium falciparum 3D7"]',
    "eda_sample_table_suffix": "s3be28bbe14_sample",
}

pytestmark = pytest.mark.skipif(
    needs_qa_recording("wdk/search_genes_by_ngs_snps.json"), reason=NEEDS_QA_RECORDING
)


async def _variant_stats(statement: list[object], reads: FilterReadsDouble) -> None:
    await resolve_params_with_intent(
        fetch_at=serving(*variant_characteristics()),
        filter_reads=reads,
        intent=ParamIntent(),
        search_name="GenesByVariantCharacteristics",
        stated={"organism_select_none": _PF, "gene_variant_stats": statement},
    )


async def _samples(statement: list[object], reads: FilterReadsDouble) -> None:
    await resolve_params_with_intent(
        fetch_at=serving(*ngs_snps()),
        filter_reads=reads,
        intent=ParamIntent(),
        search_name="GenesByNgsSnps",
        stated={"organismSinglePick": _PF, "variation_sample_meta": statement},
    )


async def test_a_range_past_the_facets_largest_value_is_refused() -> None:
    reads = FilterReadsDouble(
        {"total_variants": "ontology_term_summary_total_variants"}
    )

    with pytest.raises(EmptyRangeError) as caught:
        await _variant_stats(
            [{"field": "total_variants", "value": {"min": 4824}}], reads
        )

    assert caught.value.detail == (
        "total_variants (Total variants) on gene_variant_stats spans 1 to 4,823 "
        'variants over 5,643 records; {"min": 4824} selects none of it. '
        "State a range inside it."
    )


async def test_a_range_inside_the_facet_binds() -> None:
    reads = FilterReadsDouble(
        {"total_variants": "ontology_term_summary_total_variants"}
    )

    await _variant_stats([{"field": "total_variants", "value": {"max": 1}}], reads)

    assert len(reads.ranges_read) == 1


async def test_a_date_range_is_read_under_the_bound_organism_and_site_suffix() -> None:
    reads = FilterReadsDouble(
        {"VAR_338f1760": "ontology_term_summary_ngs_snps_collection_date"}, count=538
    )

    with pytest.raises(EmptyRangeError) as caught:
        await _samples(
            [{"field": "Collection date", "value": {"min": "2015-01-01"}}], reads
        )

    assert reads.ranges_read == [
        ("variation_sample_meta", "VAR_338f1760", _SAMPLE_CONTEXT, ())
    ]
    assert "spans 2001-11-22 to 2014-08-30 over 200 records" in caught.value.detail
    assert reads.counts_read == []


async def test_a_filter_selecting_fewer_than_its_minimum_is_refused() -> None:
    reads = FilterReadsDouble(count=1)

    with pytest.raises(TooFewSelectedError) as caught:
        await _samples([{"field": "sex", "value": ["female"]}], reads)

    assert "variation_sample_meta" in caught.value.detail
    assert "selects 1 " in caught.value.detail
    assert "at least 2" in caught.value.detail


@pytest.mark.parametrize("count", [None, 2, 538])
async def test_a_known_count_at_the_minimum_or_an_unknown_count_passes(
    count: int | None,
) -> None:
    reads = FilterReadsDouble(count=count)

    await _samples([{"field": "sex", "value": ["female"]}], reads)

    assert len(reads.counts_read) == 1


async def test_a_parameter_without_a_minimum_counts_nothing() -> None:
    reads = FilterReadsDouble(count=0)

    await _variant_stats([{"field": "most_severe_impact", "value": ["HIGH"]}], reads)

    assert reads.counts_read == []


def _declared(params: list[WDKParameter], name: str) -> WDKFilterParam:
    [param] = [p for p in params if p.name == name and isinstance(p, WDKFilterParam)]
    return param


def _collection_date() -> FilterFacet:
    facet = FilterFacets.of(_declared(ngs_snps(), "variation_sample_meta")).find(
        "Collection date"
    )
    assert facet is not None
    return facet


def _site(monkeypatch: pytest.MonkeyPatch, client: MagicMock) -> SearchCatalog:
    catalog = SearchCatalog(
        "plasmodb",
        cache_dir=Path("/nonexistent"),
        policy=CatalogPolicy(),
        spawn=MagicMock(),
    )
    service = MagicMock(get_catalog=AsyncMock(return_value=catalog))
    monkeypatch.setattr(facet_ranges, "get_wdk_client", lambda _site: client)
    monkeypatch.setattr(facet_ranges, "get_discovery_service", lambda: service)
    return catalog


async def test_the_wdk_reads_cache_one_range_and_read_the_native_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    summary = WDKOntologyTermSummary.model_validate(
        load_recorded("ontology_term_summary_ngs_snps_collection_date").json_body()
    )
    counts = WDKFilterSummaryCounts.model_validate(
        load_recorded("filter_summary_counts_ngs_snps").json_body()
    )
    client = MagicMock()
    client.get_ontology_term_summary = AsyncMock(return_value=summary)
    client.get_filter_summary_counts = AsyncMock(return_value=counts)
    _site(monkeypatch, client)
    reads = WDKFilterReads("plasmodb", "transcript", "GenesByNgsSnps")
    facet = _collection_date()

    first = await reads.range("variation_sample_meta", facet, _SAMPLE_CONTEXT, [])
    second = await reads.range("variation_sample_meta", facet, _SAMPLE_CONTEXT, [])
    count = await reads.selected(
        "variation_sample_meta", _SAMPLE_CONTEXT, FilterValue()
    )

    assert first == second
    assert first is not None
    assert (first.min, first.max, first.records) == ("2001-11-22", "2014-08-30", 200)
    client.get_ontology_term_summary.assert_awaited_once()
    assert count == 538
    client.get_filter_summary_counts.assert_awaited_once_with(
        "transcript",
        "GenesByNgsSnps",
        "variation_sample_meta",
        {**_SAMPLE_CONTEXT, "variation_sample_meta": '{"filters": []}'},
        filters=[],
    )


async def test_the_range_cache_never_holds_more_than_its_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    summary = WDKOntologyTermSummary.model_validate(
        load_recorded("ontology_term_summary_ngs_snps_collection_date").json_body()
    )
    client = MagicMock(get_ontology_term_summary=AsyncMock(return_value=summary))
    catalog = _site(monkeypatch, client)
    reads = WDKFilterReads("plasmodb", "transcript", "GenesByNgsSnps")
    facet = _collection_date()
    bound = catalog.facet_ranges.maxsize

    for day in range(bound + 5):
        sibling = StringMembers(
            field="VAR_68bb04bd",
            type="string",
            is_range=False,
            include_unknown=False,
            value=[f"stated {day}"],
        )
        await reads.range("variation_sample_meta", facet, _SAMPLE_CONTEXT, [sibling])

    assert len(catalog.facet_ranges) == bound
    assert client.get_ontology_term_summary.await_count == bound + 5


async def test_a_range_is_read_under_its_sibling_clauses() -> None:
    reads = FilterReadsDouble(
        {"total_variants": "ontology_term_summary_total_variants"},
        under_siblings={
            "total_variants": "ontology_term_summary_total_variants_under_high_impact"
        },
    )

    with pytest.raises(EmptyRangeError) as caught:
        await _variant_stats(
            [
                {"field": "most_severe_impact", "value": ["HIGH"]},
                {"field": "total_variants", "value": {"max": 1}},
            ],
            reads,
        )

    [(_, term, _, others)] = reads.ranges_read
    assert term == "total_variants"
    assert [(c.field, c.value) for c in others] == [("most_severe_impact", ["HIGH"])]
    assert "spans 2 to 4,823 variants over 3,207 records" in caught.value.detail


async def test_a_queried_options_read_carries_the_ranges_it_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exchange = WDKExchange.model_validate_json(
        (
            Path(__file__).parent
            / "fixtures"
            / "plasmodb_variant_characteristics_refresh.json"
        ).read_text()
    )
    response = WDKSearchResponse.model_validate(exchange.response_json)
    client = MagicMock()
    client.get_search_details = AsyncMock(return_value=response)
    client.get_search_details_with_params = AsyncMock(return_value=response)
    monkeypatch.setattr(searches, "get_wdk_client", lambda _site: client)
    monkeypatch.setattr(search_inspection, "get_wdk_client", lambda _site: client)
    serve_reads(monkeypatch, response, client)
    reads = FilterReadsDouble(
        {"total_variants": "ontology_term_summary_total_variants"}
    )
    monkeypatch.setattr(search_inspection, "WDKFilterReads", lambda *_: reads)

    read = await read_parameter_options(
        "plasmodb",
        "GenesByVariantCharacteristics",
        "gene_variant_stats",
        record_type="transcript",
        context_values={"organism_select_none": MultiPickValue(values=_PF)},
        narrowing=VocabNarrowing(query="variants per kb"),
    )

    assert isinstance(read, ParameterInfo)
    terms = [term for _, term, _, _ in reads.ranges_read]
    assert terms == ["variants_per_kb", "total_variants", "n_missense"]
    assert [f.term for f in read.filter_fields[:3]] == terms
    ranged = {f.term: f.range for f in read.filter_fields if f.range is not None}
    assert list(ranged) == ["total_variants"]
    assert ranged["total_variants"].text() == "1 to 4,823 variants over 5,643 records"
    assert reads.ranges_read[0][2:] == (
        {"organism_select_none": '["Plasmodium falciparum 3D7"]'},
        (),
    )

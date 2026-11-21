"""A filter statement binds to the facet it names, read under the bound parents."""

from __future__ import annotations

from pathlib import Path

import pytest
from tests._support.filter_reads import FilterReadsDouble
from veupathdb.devtools import WDKExchange
from veupathdb.domain.parameters import (
    FilterStatementError,
    FilterValue,
    NumberRange,
    StringMembers,
)
from veupathdb.testing import NEEDS_QA_RECORDING, needs_qa_recording
from veupathdb.testing.wdk_fixtures import load_recorded
from veupathdb.wdk import WDKParameter, WDKSearchResponse

from veupathdb_mcp.catalog.param_dag import resolve_params_with_intent
from veupathdb_mcp.catalog.param_intent import ParamIntent, Provenance

from .conftest import serving

_REFRESH = (
    Path(__file__).parent / "fixtures" / "plasmodb_variant_characteristics_refresh.json"
)
_PF = ["Plasmodium falciparum 3D7"]

pytestmark = pytest.mark.skipif(
    needs_qa_recording("wdk/search_genes_by_ngs_snps.json"), reason=NEEDS_QA_RECORDING
)


def variant_characteristics() -> list[WDKParameter]:
    exchange = WDKExchange.model_validate_json(_REFRESH.read_text())
    response = WDKSearchResponse.model_validate(exchange.response_json)
    return response.search_data.parameters or []


def ngs_snps() -> list[WDKParameter]:
    body = load_recorded("search_genes_by_ngs_snps").json_body()
    return WDKSearchResponse.model_validate(body).search_data.parameters or []


async def test_a_range_statement_binds_its_facet_and_reads_its_range_once() -> None:
    reads = FilterReadsDouble(
        {"total_variants": "ontology_term_summary_total_variants"}
    )

    resolved = await resolve_params_with_intent(
        fetch_at=serving(*variant_characteristics()),
        filter_reads=reads,
        intent=ParamIntent(),
        search_name="GenesByVariantCharacteristics",
        stated={
            "organism_select_none": _PF,
            "gene_variant_stats": [{"field": "total_variants", "value": {"min": 6}}],
        },
    )

    value = resolved.params["gene_variant_stats"]
    assert isinstance(value, FilterValue)
    [clause] = value.filters
    assert isinstance(clause, NumberRange)
    assert (clause.field, clause.value.min, clause.value.max) == (
        "total_variants",
        6,
        None,
    )
    assert resolved.provenance["gene_variant_stats"] is Provenance.STATED
    assert [term for _, term, _, _ in reads.ranges_read] == ["total_variants"]


async def test_a_facet_named_by_a_part_of_its_name_is_refused() -> None:
    reads = FilterReadsDouble()

    with pytest.raises(FilterStatementError) as caught:
        await resolve_params_with_intent(
            fetch_at=serving(*variant_characteristics()),
            filter_reads=reads,
            intent=ParamIntent(),
            search_name="GenesByVariantCharacteristics",
            stated={
                "organism_select_none": _PF,
                "gene_variant_stats": [{"field": "variants", "value": {"min": 6}}],
            },
        )

    assert "No facet is named 'variants'" in caught.value.detail
    assert "total_variants, variants_per_kb" in caught.value.detail
    assert reads.ranges_read == []


async def test_a_member_statement_reads_no_range_and_counts_what_it_selects() -> None:
    reads = FilterReadsDouble(count=538)

    resolved = await resolve_params_with_intent(
        fetch_at=serving(*ngs_snps()),
        filter_reads=reads,
        intent=ParamIntent(),
        search_name="GenesByNgsSnps",
        stated={
            "organismSinglePick": _PF,
            "variation_sample_meta": [{"field": "sex", "value": ["female"]}],
        },
    )

    value = resolved.params["variation_sample_meta"]
    assert isinstance(value, FilterValue)
    assert value.filters == [
        StringMembers(
            field="VAR_68bb04bd",
            type="string",
            is_range=False,
            include_unknown=False,
            value=["female"],
        )
    ]
    assert reads.ranges_read == []
    [(param, context, counted)] = reads.counts_read
    assert param == "variation_sample_meta"
    assert context == {
        "organismSinglePick": '["Plasmodium falciparum 3D7"]',
        "eda_sample_table_suffix": "s3be28bbe14_sample",
    }
    assert counted == value

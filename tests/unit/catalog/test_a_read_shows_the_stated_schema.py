"""A parameter read shows the schema its value is stated in and the facets of a filter."""

from __future__ import annotations

import pytest
from tests._support.param_infos import param_infos
from veupathdb.domain.parameters import FilterFacet
from veupathdb.testing import NEEDS_QA_RECORDING, needs_qa_recording
from veupathdb.testing.wdk_fixtures import load_recorded
from veupathdb.wdk import WDKSearchResponse

from veupathdb_mcp.catalog import ParameterInfo, build_sheet

pytestmark = pytest.mark.skipif(
    needs_qa_recording("wdk/search_genes_by_ngs_snps.json")
    or needs_qa_recording("wdk/search_genes_by_variant_characteristics.json"),
    reason=NEEDS_QA_RECORDING,
)


def _infos(fixture: str) -> dict[str, ParameterInfo]:
    body = load_recorded(fixture).json_body()
    params = WDKSearchResponse.model_validate(body).search_data.parameters or []
    return {info.name: info for info in param_infos(params)}


def test_a_small_vocabulary_is_stated_as_an_enum() -> None:
    info = _infos("search_genes_by_ngs_snps")["ReadFrequencyPercent"]

    dumped = info.model_dump(by_alias=True, mode="json")

    assert dumped["statedSchema"] == {
        "enum": ["80%", "60%", "40%", "20%"],
        "type": "string",
    }
    assert "valueFormat" not in dumped


def test_a_filter_read_shows_its_facets() -> None:
    info = _infos("search_genes_by_ngs_snps")["variation_sample_meta"]

    collection = next(f for f in info.filter_fields if f.term == "VAR_338f1760")

    assert collection == FilterFacet(
        term="VAR_338f1760",
        display="Collection date",
        parent="VAR_700f05f4",
        type="date",
        is_range=True,
        units=None,
        precision=0,
        members=[],
    )


def test_the_sheet_shows_a_range_facet_with_its_units_and_no_members() -> None:
    info = _infos("search_genes_by_variant_characteristics")["gene_variant_stats"]

    [entry] = build_sheet([info], query="")
    total = next(f for f in entry.filter_facets if f.term == "total_variants")

    assert total.units == "variants"
    assert total.is_range is True
    assert total.members == []

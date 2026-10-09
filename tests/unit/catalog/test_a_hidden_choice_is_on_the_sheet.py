"""A read-only parameter is marked as WDK marks it, and a hidden parameter
with a vocabulary is on the sheet, marked hidden, because it takes any entry."""

from __future__ import annotations

import pytest
from tests._support.recorded_searches import recorded_search
from veupathdb.testing import NEEDS_QA_RECORDING, needs_qa_recording

from veupathdb_mcp import catalog
from veupathdb_mcp.catalog.overview_formatting import format_search_overview
from veupathdb_mcp.catalog.param_formatting import format_param_info_typed
from veupathdb_mcp.catalog.param_sheet import build_sheet


def _infos(fixture: str) -> list[catalog.ParameterInfo]:
    return format_param_info_typed(
        recorded_search(fixture).search_data.parameters or []
    )


@pytest.mark.skipif(
    needs_qa_recording(
        "wdk/search_genes_by_ngs_snps.json", "wdk/search_genes_by_orthologs.json"
    ),
    reason=NEEDS_QA_RECORDING,
)
def test_only_the_parameters_wdk_marks_read_only_are_read_only() -> None:
    marked = {
        fixture: [info.name for info in _infos(fixture) if info.is_read_only]
        for fixture in ("search_genes_by_orthologs", "search_genes_by_ngs_snps")
    }

    assert marked == {
        "search_genes_by_orthologs": ["gene_result"],
        "search_genes_by_ngs_snps": [],
    }


@pytest.mark.skipif(
    needs_qa_recording("wdk/search_genes_by_orthologs.json"), reason=NEEDS_QA_RECORDING
)
def test_the_read_only_mark_travels_on_the_wire() -> None:
    by_name = {info.name: info for info in _infos("search_genes_by_orthologs")}

    assert by_name["gene_result"].model_dump(by_alias=True)["isReadOnly"] is True


@pytest.mark.skipif(
    needs_qa_recording("wdk/search_genes_by_ngs_snps.json"), reason=NEEDS_QA_RECORDING
)
def test_a_hidden_parameter_with_a_vocabulary_is_on_the_sheet_marked_hidden() -> None:
    sheet = build_sheet(_infos("search_genes_by_ngs_snps"), query="snps")

    assert [(e.name, e.default) for e in sheet if e.hidden] == [
        ("eda_sample_table_suffix", "s3be28bbe14_sample"),
        ("WebServicesPath", "dflt"),
    ]
    assert len([e for e in sheet if not e.hidden]) == 12


@pytest.mark.skipif(
    needs_qa_recording("wdk/search_with_a_hidden_required_parameter.json"),
    reason=NEEDS_QA_RECORDING,
)
def test_a_hidden_parameter_without_a_vocabulary_is_not_on_the_sheet() -> None:
    names = [
        e.name
        for e in build_sheet(
            _infos("search_with_a_hidden_required_parameter"), query="genes"
        )
    ]

    assert "eda_dataset_id" not in names


@pytest.mark.skipif(
    needs_qa_recording("wdk/search_genes_by_ngs_snps.json"), reason=NEEDS_QA_RECORDING
)
def test_the_overview_still_lists_only_visible_parameters() -> None:
    response = recorded_search("search_genes_by_ngs_snps")

    overview = format_search_overview(
        definition=response.search_data,
        record_type="transcript",
        infos=_infos("search_genes_by_ngs_snps"),
        query="snps",
    )

    names = {e.name for e in overview.required + overview.optional}
    assert (len(names), names & {"eda_sample_table_suffix", "WebServicesPath"}) == (
        12,
        set(),
    )

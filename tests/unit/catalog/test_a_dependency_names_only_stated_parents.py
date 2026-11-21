from __future__ import annotations

import json

import pytest
from tests._support.recorded_searches import recorded_search
from tests._support.recordings import TEST_ROOT
from veupathdb.testing import NEEDS_QA_RECORDING, needs_qa_recording
from veupathdb.wdk import WDKSearchResponse

from veupathdb_mcp.catalog import adapt_param_specs_from_search, format_param_info_typed
from veupathdb_mcp.catalog.param_formatting import ParameterInfo


def _snps() -> dict[str, ParameterInfo]:
    params = recorded_search("search_genes_by_ngs_snps").search_data.parameters or []
    return {info.name: info for info in format_param_info_typed(params)}


def _text() -> dict[str, ParameterInfo]:
    path = TEST_ROOT / "unit/audit/fixtures/gene_ids_pfalNF54_piga.json"
    raw = json.loads(path.read_text())["search"]
    params = WDKSearchResponse.model_validate(raw).search_data.parameters or []
    return {info.name: info for info in format_param_info_typed(params)}


snps_recorded = pytest.mark.skipif(
    needs_qa_recording("wdk/search_genes_by_ngs_snps.json"), reason=NEEDS_QA_RECORDING
)


@snps_recorded
def test_a_dependent_names_its_stated_parent_and_keeps_the_wire_parents() -> None:
    info = _snps()["variation_sample_meta"]

    assert info.stated_parents == ["organismSinglePick"]
    assert info.wire_parents == ["organismSinglePick", "eda_sample_table_suffix"]


@snps_recorded
def test_a_parent_names_its_stated_child_and_keeps_the_wire_children() -> None:
    info = _snps()["organismSinglePick"]

    assert info.stated_children == ["variation_sample_meta"]
    assert info.wire_children == ["eda_sample_table_suffix", "variation_sample_meta"]


@snps_recorded
def test_the_serialized_parameter_carries_only_the_stated_links() -> None:
    dumped = _snps()["variation_sample_meta"].model_dump(by_alias=True, mode="json")

    assert {
        "vocabDependsOn",
        "controlsVocabOf",
        "wireParents",
        "wireChildren",
    }.isdisjoint(dumped)
    assert dumped["statedParents"] == ["organismSinglePick"]
    assert dumped["statedChildren"] == []


@snps_recorded
def test_the_no_context_note_names_the_stated_parent_only() -> None:
    note = _snps()["variation_sample_meta"].note

    assert note is not None
    assert "organismSinglePick" in note
    assert "eda_sample_table_suffix" not in note


@snps_recorded
def test_a_hidden_parameter_is_site_set_and_states_its_default() -> None:
    hidden = _snps()["eda_sample_table_suffix"]
    shown = _snps()["organismSinglePick"]

    assert (hidden.site_set, hidden.bindable) == (True, False)
    assert hidden.site_value == hidden.default_value is not None
    assert (shown.site_set, shown.bindable, shown.site_value) == (False, True, None)


def test_a_read_only_parent_leaves_its_child_no_note() -> None:
    info = _text()["text_fields"]

    assert info.note is None
    assert info.stated_parents == []
    assert info.wire_parents == ["document_type"]


def test_a_read_only_parameter_is_site_set() -> None:
    info = _text()["document_type"]

    assert (info.is_read_only, info.site_set, info.bindable) == (True, True, False)


def test_a_normalized_spec_keeps_the_read_only_mark() -> None:
    path = TEST_ROOT / "unit/audit/fixtures/gene_ids_pfalNF54_piga.json"
    raw = json.loads(path.read_text())["search"]
    specs = adapt_param_specs_from_search(
        WDKSearchResponse.model_validate(raw).search_data
    )

    assert (specs["document_type"].is_read_only, specs["document_type"].site_set) == (
        True,
        True,
    )
    assert specs["text_fields"].bindable is True

"""Every value the catalog shows a model is the stated form, which the stated reader reads back to the same wire."""

from __future__ import annotations

import pytest
from veupathdb.domain.parameters import (
    FilterFacets,
    FilterProposals,
    KeptValue,
    MultiPickValue,
    ParameterCanonicalizer,
    ParamGraph,
    ParamValue,
    stated_form,
)
from veupathdb.testing import NEEDS_QA_RECORDING, needs_qa_recording
from veupathdb.testing.wdk_fixtures import load_recorded
from veupathdb.wdk import WDKParameter, WDKSearchResponse

from veupathdb_mcp.catalog.param_adapters import adapt_param_from_wdk
from veupathdb_mcp.catalog.param_formatting import (
    format_param_info_typed,
    format_typed_param,
)
from veupathdb_mcp.catalog.param_sheet import build_sheet
from veupathdb_mcp.catalog.param_specs_formatting import build_param_specs_from_list

_SNPS = "search_genes_by_ngs_snps"
_SEARCHES = (
    _SNPS,
    "search_genes_by_orthologs",
    "search_genes_by_variant_characteristics",
)
_RECORDED = needs_qa_recording(*(f"wdk/{name}.json" for name in _SEARCHES))


def _params(fixture: str) -> list[WDKParameter]:
    search = WDKSearchResponse.model_validate(load_recorded(fixture).json_body())
    return search.search_data.parameters or []


def _held(param: WDKParameter) -> ParamValue:
    wire = param.initial_display_value or ""
    canonicalizer = ParameterCanonicalizer({param.name: adapt_param_from_wdk(param)})
    return canonicalizer.held({param.name: wire})[param.name]


@pytest.mark.skipif(_RECORDED, reason=NEEDS_QA_RECORDING)
class TestTheSheetDefault:
    def test_a_filter_with_no_clause_shows_as_kept(self) -> None:
        sheet = {
            e.name: e
            for e in build_sheet(format_param_info_typed(_params(_SNPS)), query="")
        }

        assert sheet["variation_sample_meta"].default == (
            "'{\"filters\": []}' (kept as the site holds it)"
        )
        assert sheet["organismSinglePick"].default == ["Plasmodium falciparum 3D7"]

    def test_an_empty_default_a_parameter_refuses_is_no_default(self) -> None:
        params = _params("search_genes_by_orthologs")
        sheet = {
            e.name: e for e in build_sheet(format_param_info_typed(params), query="")
        }

        assert sheet["organism"].default is None
        assert sheet["isSyntenic"].default == "no"

    @pytest.mark.parametrize("fixture", _SEARCHES)
    def test_every_default_not_kept_reads_back_to_its_wire(self, fixture: str) -> None:
        params = {p.name: p for p in _params(fixture)}
        sheet = build_sheet(format_param_info_typed(list(params.values())), query="")
        checked = 0
        for entry in sheet:
            param = params[entry.name]
            held = _held(param)
            if entry.default is None or isinstance(stated_form(held), KeptValue):
                continue
            read = param.read_stated(entry.default)
            if isinstance(read, FilterProposals):
                read = FilterFacets.of(param).bind(read)
            assert read.to_wire() == held.to_wire(), entry.name
            checked += 1

        assert checked > 0


@pytest.mark.skipif(_RECORDED, reason=NEEDS_QA_RECORDING)
def test_the_note_names_a_bound_parent_in_its_stated_form() -> None:
    params = _params(_SNPS)
    child = next(p for p in params if p.name == "variation_sample_meta")

    info = format_typed_param(
        child,
        ParamGraph.of(params),
        applied_context={
            "organismSinglePick": MultiPickValue(values=["Plasmodium falciparum 3D7"])
        },
    )

    assert info.note is not None
    assert 'organismSinglePick=["Plasmodium falciparum 3D7"]' in info.note


@pytest.mark.skipif(_RECORDED, reason=NEEDS_QA_RECORDING)
def test_a_param_spec_shows_the_default_as_stated_beside_the_wire() -> None:
    specs = {s.name: s for s in build_param_specs_from_list(_params(_SNPS))}

    organism = specs["organismSinglePick"]
    assert organism.initial_display_value == '["Plasmodium falciparum 3D7"]'
    assert organism.default == ["Plasmodium falciparum 3D7"]
    assert specs["variation_sample_meta"].default == (
        "'{\"filters\": []}' (kept as the site holds it)"
    )

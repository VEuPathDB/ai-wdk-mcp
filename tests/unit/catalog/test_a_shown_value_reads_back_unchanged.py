"""Every value the catalog shows a model is the stated form, which the stated reader reads back to the same wire."""

from __future__ import annotations

import json

import pytest
from veupathdb.domain.parameters import (
    FilterFacets,
    FilterProposals,
    FilterValue,
    KeptValue,
    MultiPickValue,
    ParameterCanonicalizer,
    ParamGraph,
    ParamValue,
    UnboundParameter,
    stated_form,
)
from veupathdb.testing import NEEDS_QA_RECORDING, needs_qa_recording
from veupathdb.testing.wdk_fixtures import load_recorded
from veupathdb.wdk import WDKParameter, WDKSearchResponse

from veupathdb_mcp.catalog._param_filters import _resolve_filter_param
from veupathdb_mcp.catalog.param_adapters import adapt_param_from_wdk
from veupathdb_mcp.catalog.param_formatting import (
    format_param_info_typed,
    format_typed_param,
)
from veupathdb_mcp.catalog.param_sheet import build_sheet
from veupathdb_mcp.catalog.param_specs_formatting import (
    build_param_specs_from_list,
    build_stated_param_specs,
)

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
class TestTheParamSpecs:
    def test_the_web_spec_carries_the_wire_alone(self) -> None:
        specs = {s.name: s for s in build_param_specs_from_list(_params(_SNPS))}

        organism = specs["organismSinglePick"].model_dump(by_alias=True)
        assert organism["initialDisplayValue"] == '["Plasmodium falciparum 3D7"]'
        assert "default" not in organism

    def test_the_served_spec_carries_the_stated_default_alone(self) -> None:
        params = _params(_SNPS)
        search = WDKSearchResponse.model_validate(load_recorded(_SNPS).json_body())
        specs = {s.name: s for s in build_stated_param_specs(search.search_data)}

        organism = specs["organismSinglePick"].model_dump(by_alias=True)
        assert organism["default"] == ["Plasmodium falciparum 3D7"]
        assert "initialDisplayValue" not in organism
        assert specs["variation_sample_meta"].default == (
            "'{\"filters\": []}' (kept as the site holds it)"
        )
        assert set(specs) == {p.name for p in params}


@pytest.mark.skipif(_RECORDED, reason=NEEDS_QA_RECORDING)
def test_every_contrast_option_reads_back_to_its_filter() -> None:
    params = {p.name: p for p in _params(_SNPS)}
    param = params["variation_sample_meta"]
    [info] = format_param_info_typed([param])
    ref = info.model_copy(update={"name": "ref_samples"})
    comp = info.model_copy(update={"name": "comp_samples"})

    slot = _resolve_filter_param(ref, [ref, comp], {})

    assert isinstance(slot, UnboundParameter)
    assert slot.options
    for option in slot.options:
        stated = json.loads(option)
        assert isinstance(stated, list)
        read = param.read_stated(stated)
        assert isinstance(read, FilterProposals)
        [proposal] = read.root
        facet = next(f for f in FilterFacets.of(param).root if f.term == proposal.field)
        expected = FilterValue(filters=[facet.clause(proposal)])
        assert FilterFacets.of(param).bind(read).to_wire() == expected.to_wire()

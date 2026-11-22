from __future__ import annotations

import pytest
from fastmcp.exceptions import ToolError
from tests._support.filter_reads import FilterReadsDouble
from tests._support.param_infos import param_infos
from tests._support.recorded_searches import recorded_search
from tests._support.wdk_reads import serve_reads
from veupathdb.domain import SearchContext
from veupathdb.domain.parameters import StringValue
from veupathdb.errors import ValidationError
from veupathdb.testing import NEEDS_QA_RECORDING, needs_qa_recording
from veupathdb.wdk import WDKEnumParam, WDKParameter, WDKSearchResponse, WDKStringParam

from veupathdb_mcp.catalog import (
    ParamIntent,
    PhyleticListError,
    SiteSetParameterError,
    UnknownParameterError,
    build_param_specs,
    resolve_params_with_intent,
    search_inspection,
)
from veupathdb_mcp.catalog.overview_formatting import format_search_overview
from veupathdb_mcp.tools import catalog_tools

from .conftest import serving, vocab_terms

pytestmark = pytest.mark.skipif(
    needs_qa_recording("wdk/search_genes_by_ngs_snps.json"), reason=NEEDS_QA_RECORDING
)

HIDDEN = {"eda_sample_table_suffix", "WebServicesPath"}
SEARCH = "GenesByNgsSnps"


def _snps() -> WDKSearchResponse:
    return recorded_search("search_genes_by_ngs_snps")


@pytest.fixture
def served(monkeypatch: pytest.MonkeyPatch) -> None:
    async def record_type(site_id: str, search_name: str, wanted: str | None) -> str:
        del site_id, search_name, wanted
        return "transcript"

    async def under_context(*args: object, **kwargs: object) -> WDKSearchResponse:
        del args, kwargs
        return _snps()

    async def definition(site_id: str, rt: str, search_name: str) -> object:
        del site_id, rt, search_name
        return _snps().search_data

    monkeypatch.setattr(search_inspection, "resolve_search_record_type", record_type)
    monkeypatch.setattr(
        search_inspection, "get_search_params_under_context", under_context
    )
    monkeypatch.setattr(search_inspection, "read_search_definition", definition)
    monkeypatch.setattr(search_inspection, "get_wdk_client", lambda site_id: None)
    serve_reads(monkeypatch, _snps())


@pytest.mark.usefixtures("served")
async def test_the_options_of_a_hidden_parameter_are_refused_by_name() -> None:
    with pytest.raises(SiteSetParameterError) as refused:
        await search_inspection.read_parameter_options(
            "plasmodb", SEARCH, "eda_sample_table_suffix"
        )

    assert refused.value.detail == (
        "eda_sample_table_suffix on GenesByNgsSnps is set by the site: the website "
        "does not offer it, and it is sent at the value the site gives it under the "
        "other values. Leave it out."
    )


@pytest.mark.usefixtures("served")
async def test_the_served_options_read_answers_the_refusal_as_a_tool_error() -> None:
    with pytest.raises(ToolError, match="is set by the site"):
        await catalog_tools.get_parameter_options("plasmodb", SEARCH, "WebServicesPath")


@pytest.mark.usefixtures("served")
async def test_a_visible_parameters_options_name_no_hidden_parameter() -> None:
    read = await search_inspection.read_parameter_options(
        "plasmodb", SEARCH, "organismSinglePick"
    )

    assert read.name == "organismSinglePick"
    assert read.stated_children == ["variation_sample_meta"]


@pytest.mark.usefixtures("served")
async def test_the_served_specs_list_visible_parameters_only() -> None:
    specs = await catalog_tools.get_search_param_specs("plasmodb", SEARCH)

    names = {spec.name for spec in specs}
    assert (len(names), names & HIDDEN) == (12, set())
    wdk = {
        p.name: list(p.dependent_params) for p in _snps().search_data.parameters or []
    }
    assert all(spec.dependent_params == wdk[spec.name] for spec in specs)


def test_a_hosts_spec_builder_keeps_every_parameter() -> None:
    names = {spec.name for spec in build_param_specs(_snps().search_data)}

    assert names >= HIDDEN


def test_the_overview_names_no_hidden_parameter_as_controlled() -> None:
    overview = format_search_overview(
        definition=_snps().search_data,
        record_type="transcript",
        infos=param_infos(_snps().search_data.parameters or []),
        query="snps",
    )

    controlled = {
        name
        for entry in overview.required + overview.optional
        for name in entry.controls_vocab_of or []
    }
    assert controlled == {"variation_sample_meta"}


async def test_the_resolve_walk_binds_a_hidden_parameter_at_its_default() -> None:
    stated = WDKStringParam(name="stated_by_you", allow_empty_value=False)
    definition = [*(_snps().search_data.parameters or []), stated]

    resolved = await resolve_params_with_intent(
        filter_reads=FilterReadsDouble(),
        fetch_at=serving(*definition),
        search=SearchContext("plasmodb", "transcript", SEARCH),
        intent=ParamIntent(),
        stated={},
        about=None,
    )

    assert {name: resolved.params[name].to_wire() for name in HIDDEN} == {
        "eda_sample_table_suffix": "s3be28bbe14_sample",
        "WebServicesPath": "dflt",
    }
    assert [slot.param_name for slot in resolved.open_slots] == ["stated_by_you"]
    assert resolved.unresolved_required == ["stated_by_you"]


async def test_a_hidden_required_parameter_with_no_default_refuses_the_search() -> None:
    unset = WDKStringParam(name="site_only", is_visible=False, allow_empty_value=False)
    definition = [*(_snps().search_data.parameters or []), unset]

    with pytest.raises(SiteSetParameterError) as refused:
        await resolve_params_with_intent(
            filter_reads=FilterReadsDouble(),
            fetch_at=serving(*definition),
            intent=ParamIntent(),
            search=SearchContext("plasmodb", "transcript", SEARCH),
            stated={},
            about=None,
        )

    assert refused.value.detail == (
        "site_only on GenesByNgsSnps is set by the site, and the site gives it no "
        "value, so the search cannot run from the values given."
    )


@pytest.mark.skipif(
    needs_qa_recording("wdk/search_genes_by_orthologs.json"), reason=NEEDS_QA_RECORDING
)
async def test_a_hidden_input_step_is_left_to_the_step_tree() -> None:
    definition = recorded_search("search_genes_by_orthologs").search_data.parameters

    resolved = await resolve_params_with_intent(
        filter_reads=FilterReadsDouble(),
        fetch_at=serving(*(definition or [])),
        search=SearchContext("plasmodb", "transcript", SEARCH),
        intent=ParamIntent(),
        stated={},
        about=None,
    )

    assert "gene_result" not in resolved.unresolved_required
    assert "gene_result" not in {slot.param_name for slot in resolved.open_slots}


async def test_the_resolve_walk_refuses_a_hidden_override_by_name() -> None:
    definition = _snps().search_data.parameters or []

    with pytest.raises(SiteSetParameterError) as refused:
        await resolve_params_with_intent(
            filter_reads=FilterReadsDouble(),
            fetch_at=serving(*definition),
            intent=ParamIntent(),
            stated={"WebServicesPath": "dflt"},
            search=SearchContext("plasmodb", "transcript", SEARCH),
            about=None,
        )

    assert refused.value.detail == (
        "WebServicesPath on GenesByNgsSnps is set by the site: the website does not "
        "offer it, and it is sent at the value the site gives it under the other "
        "values. Leave it out."
    )


def _profile_search() -> list[WDKParameter]:
    def tree_map(name: str, pairs: list[tuple[str, str]]) -> WDKParameter:
        return WDKEnumParam(
            name=name,
            type="multi-pick-vocabulary",
            is_visible=False,
            allow_empty_value=True,
            initial_display_value="[]",
            vocabulary=vocab_terms(*pairs),
        )

    return [
        WDKStringParam(
            name="profile_pattern",
            is_visible=False,
            allow_empty_value=False,
            initial_display_value="hsap=1T",
        ),
        WDKStringParam(name="included_species", allow_empty_value=True),
        WDKStringParam(name="excluded_species", allow_empty_value=True),
        tree_map(
            "phyletic_term_map",
            [
                ("ALL", "Root"),
                ("EUKA", "Eukaryota"),
                ("hsap", "Homo sapiens"),
                ("pfal", "Plasmodium falciparum 3D7"),
            ],
        ),
        tree_map("phyletic_indent_map", [("EUKA", "1"), ("hsap", "2"), ("pfal", "2")]),
    ]


async def test_the_walk_derives_profile_pattern_from_the_two_lists() -> None:
    definition = _profile_search()

    resolved = await resolve_params_with_intent(
        filter_reads=FilterReadsDouble(),
        fetch_at=serving(*definition),
        search=SearchContext("plasmodb", "transcript", SEARCH),
        intent=ParamIntent(),
        stated={"included_species": "pfal", "excluded_species": "hsap"},
        about=None,
    )

    assert resolved.params["profile_pattern"] == StringValue(value="%hsap:N%pfal:Y%")
    assert resolved.provenance["profile_pattern"].value == "stated"


@pytest.mark.parametrize(
    "name", ["profile_pattern", "phyletic_term_map", "phyletic_indent_map"]
)
async def test_a_stated_phyletic_value_is_refused_by_name(name: str) -> None:
    definition = _profile_search()

    with pytest.raises(ValidationError, match=name):
        await resolve_params_with_intent(
            filter_reads=FilterReadsDouble(),
            fetch_at=serving(*definition),
            search=SearchContext("plasmodb", "transcript", SEARCH),
            intent=ParamIntent(),
            stated={"included_species": "pfal", name: "%pfal:Y%"},
            about=None,
        )


async def test_lists_that_name_no_entry_are_refused_with_the_nearest() -> None:
    definition = _profile_search()

    with pytest.raises(PhyleticListError, match="included_species names no entry"):
        await resolve_params_with_intent(
            filter_reads=FilterReadsDouble(),
            fetch_at=serving(*definition),
            search=SearchContext("plasmodb", "transcript", SEARCH),
            intent=ParamIntent(),
            stated={"included_species": "Plasmodium vivax"},
            about=None,
        )


def _serve_profile_search(monkeypatch: pytest.MonkeyPatch) -> None:
    definition = _profile_search()

    monkeypatch.setattr(
        catalog_tools,
        "wdk_fetch_at",
        lambda *args: serving(*definition),
    )


async def test_the_served_resolve_derives_profile_pattern_from_its_definition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _serve_profile_search(monkeypatch)

    resolved = await catalog_tools.resolve_search_parameters(
        "plasmodb",
        "GenesByOrthologPattern",
        overrides={"included_species": "pfal", "excluded_species": "hsap"},
    )

    assert resolved.params["profile_pattern"] == StringValue(value="%hsap:N%pfal:Y%")


async def test_the_served_resolve_refuses_a_stated_profile_pattern(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _serve_profile_search(monkeypatch)

    with pytest.raises(
        ToolError, match="profile_pattern on GenesByOrthologPattern is set by the site"
    ):
        await catalog_tools.resolve_search_parameters(
            "plasmodb",
            "GenesByOrthologPattern",
            overrides={"profile_pattern": "%pfal:Y%"},
        )


async def test_a_phyletic_search_with_neither_list_is_refused() -> None:
    definition = _profile_search()

    with pytest.raises(PhyleticListError, match="select no species"):
        await resolve_params_with_intent(
            filter_reads=FilterReadsDouble(),
            fetch_at=serving(*definition),
            search=SearchContext("plasmodb", "transcript", SEARCH),
            intent=ParamIntent(),
            stated={},
            about=None,
        )


async def test_an_unknown_name_lists_only_the_visible_names() -> None:
    definition = _profile_search()

    with pytest.raises(UnknownParameterError) as refused:
        await resolve_params_with_intent(
            filter_reads=FilterReadsDouble(),
            fetch_at=serving(*definition),
            search=SearchContext("plasmodb", "transcript", SEARCH),
            intent=ParamIntent(),
            stated={"included_species": "pfal", "speciess": "x"},
            about=None,
        )

    assert refused.value.valid == ["excluded_species", "included_species"]

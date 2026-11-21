from __future__ import annotations

import json
from collections.abc import Callable

import pytest
from tests._support.recorded_searches import recorded_search
from tests._support.recordings import TEST_ROOT
from veupathdb.testing import NEEDS_QA_RECORDING, needs_qa_recording
from veupathdb.wdk import WDKParameter, WDKSearchResponse, WDKStringParam

from veupathdb_mcp.catalog import (
    ParamIntent,
    SiteSetParameterError,
    UnknownParameterError,
    format_param_info_typed,
    resolve_params_with_intent,
    search_inspection,
)
from veupathdb_mcp.catalog.overview_formatting import format_search_overview
from veupathdb_mcp.catalog.param_formatting import (
    ParameterInfo,
    ParameterNotOnSearch,
    ParentContextRequired,
)
from veupathdb_mcp.catalog.param_sheet import build_sheet
from veupathdb_mcp.tools import catalog_tools

from .conftest import serving

SNPS = "GenesByNgsSnps"
HIDDEN = {"eda_sample_table_suffix", "WebServicesPath"}

snps_recorded = pytest.mark.skipif(
    needs_qa_recording("wdk/search_genes_by_ngs_snps.json"), reason=NEEDS_QA_RECORDING
)


def _snps() -> WDKSearchResponse:
    return recorded_search("search_genes_by_ngs_snps")


def _text() -> WDKSearchResponse:
    path = TEST_ROOT / "unit/audit/fixtures/gene_ids_pfalNF54_piga.json"
    return WDKSearchResponse.model_validate(json.loads(path.read_text())["search"])


@pytest.fixture
def serve(monkeypatch: pytest.MonkeyPatch) -> Callable[[WDKSearchResponse], None]:
    def install(response: WDKSearchResponse) -> None:
        async def record_type(site_id: str, search_name: str, wanted: object) -> str:
            del site_id, search_name, wanted
            return "transcript"

        async def under_context(*args: object, **kwargs: object) -> WDKSearchResponse:
            del args, kwargs
            return response

        async def definition(site_id: str, rt: str, search_name: str) -> object:
            del site_id, rt, search_name
            return response.search_data

        monkeypatch.setattr(
            search_inspection, "resolve_search_record_type", record_type
        )
        monkeypatch.setattr(
            search_inspection, "get_search_params_under_context", under_context
        )
        monkeypatch.setattr(search_inspection, "read_search_definition", definition)
        monkeypatch.setattr(search_inspection, "get_wdk_client", lambda site_id: None)

    return install


@snps_recorded
async def test_a_dependent_reads_under_its_stated_parent_alone(
    serve: Callable[[WDKSearchResponse], None],
) -> None:
    serve(_snps())

    read = await search_inspection.read_parameter_options(
        "plasmodb",
        SNPS,
        "variation_sample_meta",
        context_values={"organismSinglePick": ["Plasmodium falciparum 3D7"]},
    )

    assert isinstance(read, ParameterInfo)
    assert read.name == "variation_sample_meta"


@snps_recorded
async def test_a_dependent_without_context_names_only_its_stated_parent(
    serve: Callable[[WDKSearchResponse], None],
) -> None:
    serve(_snps())

    read = await search_inspection.read_parameter_options(
        "plasmodb", SNPS, "variation_sample_meta"
    )

    assert isinstance(read, ParentContextRequired)
    assert read.parent_parameter_ids == ["organismSinglePick"]


async def test_a_child_of_a_read_only_parent_reads_without_context(
    serve: Callable[[WDKSearchResponse], None],
) -> None:
    serve(_text())

    read = await search_inspection.read_parameter_options(
        "plasmodb", "GenesByText", "text_fields"
    )

    assert isinstance(read, ParameterInfo)
    assert "primary_key" in {option.value for option in read.vocabulary()}


@snps_recorded
def test_the_overview_and_the_sheet_name_only_the_stated_parent() -> None:
    infos = format_param_info_typed(_snps().search_data.parameters or [])

    overview = format_search_overview(
        definition=_snps().search_data,
        record_type="transcript",
        infos=infos,
        query="snps",
    )
    sheet = {entry.name: entry for entry in build_sheet(infos, query="snps")}

    assert overview.dependencies["variation_sample_meta"].depends_on == [
        "organismSinglePick"
    ]
    assert sheet["variation_sample_meta"].depends_on == ["organismSinglePick"]


@snps_recorded
async def test_an_unknown_name_suggests_no_site_set_parameter(
    serve: Callable[[WDKSearchResponse], None],
) -> None:
    serve(_snps())

    read = await search_inspection.read_parameter_options(
        "plasmodb", SNPS, "eda_sample_table_sufix"
    )

    assert isinstance(read, ParameterNotOnSearch)
    assert HIDDEN.isdisjoint(read.valid_parameter_ids)
    assert HIDDEN.isdisjoint(read.suggestions)
    assert len(read.valid_parameter_ids) == 12


@snps_recorded
async def test_reading_a_site_set_parameter_is_refused_in_the_sites_words(
    serve: Callable[[WDKSearchResponse], None],
) -> None:
    serve(_snps())

    with pytest.raises(SiteSetParameterError) as refused:
        await search_inspection.read_parameter_options(
            "plasmodb", SNPS, "eda_sample_table_suffix"
        )

    assert str(refused.value.detail) == (
        "eda_sample_table_suffix on GenesByNgsSnps is set by the site: the website "
        "does not offer it, and it is sent at the value the site gives it under the "
        "other values. Leave it out."
    )


def _read_only_definition() -> list[WDKParameter]:
    return [
        WDKStringParam(
            name="fixed",
            is_read_only=True,
            allow_empty_value=False,
            initial_display_value="gene",
        ),
        WDKStringParam(name="text", allow_empty_value=False),
    ]


def _read_only_search() -> list[ParameterInfo]:
    return format_param_info_typed(_read_only_definition())


def test_a_visible_read_only_parameter_is_off_the_sheet() -> None:
    names = [entry.name for entry in build_sheet(_read_only_search(), query="x")]

    assert names == ["text"]


async def test_an_override_of_a_visible_read_only_parameter_is_refused() -> None:
    with pytest.raises(SiteSetParameterError, match="fixed"):
        await resolve_params_with_intent(
            fetch_at=serving(*_read_only_definition()),
            search_name="GenesByReadOnly",
            intent=ParamIntent(),
            stated={"fixed": "gene", "text": "kinase"},
        )


@snps_recorded
async def test_the_served_specs_list_visible_parameters_with_their_read_only_mark(
    serve: Callable[[WDKSearchResponse], None],
) -> None:
    serve(_snps())

    specs = await catalog_tools.get_search_param_specs("plasmodb", SNPS)

    visible = {p.name for p in _snps().search_data.parameters or [] if p.is_visible}
    dumped = {spec.name: spec.model_dump(by_alias=True) for spec in specs}
    assert set(dumped) == visible
    assert all(entry["isReadOnly"] is False for entry in dumped.values())
    assert dumped["organismSinglePick"]["dependentParams"] == [
        "eda_sample_table_suffix",
        "variation_sample_meta",
    ]


async def test_an_unknown_override_lists_no_read_only_name() -> None:
    with pytest.raises(UnknownParameterError) as refused:
        await resolve_params_with_intent(
            fetch_at=serving(*_read_only_definition()),
            search_name="GenesByReadOnly",
            intent=ParamIntent(),
            stated={"txt": "kinase"},
        )

    assert refused.value.valid == ["text"]

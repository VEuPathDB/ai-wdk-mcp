"""The organism parameter is the one WDK marks, whatever its name."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from tests._support.recorded_searches import recorded_search
from veupathdb.domain import SearchContext
from veupathdb.wdk import WDKSearchResponse

from veupathdb_mcp import catalog
from veupathdb_mcp.catalog import searches
from veupathdb_mcp.catalog.overview_formatting import format_search_overview
from veupathdb_mcp.catalog.param_formatting import format_param_info_typed
from veupathdb_mcp.catalog.param_sheet import build_sheet

MARKED = [
    ("search_genes_by_ngs_snps", "organismSinglePick"),
    ("search_genes_by_gene_model_chars", "organism_select_none"),
    ("search_genes_by_molecular_weight", "organism"),
]
# The site each recorded search came from.
RECORDED_ON = {
    "search_genes_by_ngs_snps": "plasmodb",
    "search_genes_by_gene_model_chars": "vectorbase",
    "search_genes_by_molecular_weight": "plasmodb",
}


def _infos(fixture: str) -> list[catalog.ParameterInfo]:
    definition = recorded_search(fixture).search_data
    return format_param_info_typed(definition.parameters or [])


@pytest.mark.parametrize(("fixture", "marked"), MARKED)
def test_only_the_marked_parameter_is_the_organism_parameter(
    fixture: str, marked: str
) -> None:
    infos = _infos(fixture)

    assert [info.name for info in infos if info.organism_param] == [marked]


def test_the_mark_travels_on_the_wire() -> None:
    by_name = {info.name: info for info in _infos("search_genes_by_ngs_snps")}

    assert by_name["organismSinglePick"].model_dump(by_alias=True)["organismParam"]
    assert not by_name["snp_class"].model_dump(by_alias=True)["organismParam"]


@pytest.mark.parametrize(("fixture", "marked"), MARKED)
def test_the_sheet_names_the_organism_parameter(fixture: str, marked: str) -> None:
    sheet = build_sheet(_infos(fixture), query="genes")

    assert [entry.name for entry in sheet if entry.organism_param] == [marked]


def test_the_overview_names_the_organism_parameter() -> None:
    response = recorded_search("search_genes_by_gene_model_chars")

    overview = format_search_overview(
        definition=response.search_data,
        record_type="transcript",
        infos=_infos("search_genes_by_gene_model_chars"),
        query="genes",
    )

    entries = overview.required + overview.optional
    assert [entry.name for entry in entries if entry.organism_param] == [
        "organism_select_none"
    ]


_FIXTURES = Path(__file__).parent / "fixtures"


def _site_search(name: str) -> WDKSearchResponse:
    """A plasmodb definition this suite recorded whole."""
    recorded = json.loads((_FIXTURES / f"{name}.json").read_text())
    return WDKSearchResponse.model_validate(recorded["response_json"])


def _serving(
    monkeypatch: pytest.MonkeyPatch,
    by_search: dict[str, WDKSearchResponse],
    site_id: str = "plasmodb",
) -> MagicMock:
    """Each search's definition from ``by_search``, and the site's recorded
    GenesByTaxon, whose marked parameter lists the site's organisms."""
    taxon = _site_search(f"{site_id}_genes_by_taxon")
    served = {"GenesByTaxon": taxon, **by_search}

    async def _details(ctx: SearchContext) -> WDKSearchResponse:
        return served[ctx.search_name]

    discovery = MagicMock()
    discovery.get_search_details = AsyncMock(side_effect=_details)
    monkeypatch.setattr(searches, "get_discovery_service", lambda: discovery)
    return discovery


def _discovery(monkeypatch: pytest.MonkeyPatch, fixture: str) -> MagicMock:
    response = recorded_search(fixture)
    return _serving(
        monkeypatch,
        {response.search_data.url_segment: response},
        RECORDED_ON.get(fixture, "plasmodb"),
    )


class TestOrganismParameter:
    def test_a_host_reads_it_from_the_package(self) -> None:
        assert catalog.organism_parameter is searches.organism_parameter
        assert "organism_parameter" in catalog.__all__

    @pytest.mark.parametrize(("fixture", "marked"), MARKED)
    async def test_it_names_the_marked_parameter(
        self, monkeypatch: pytest.MonkeyPatch, fixture: str, marked: str
    ) -> None:
        discovery = _discovery(monkeypatch, fixture)
        search_name = recorded_search(fixture).search_data.url_segment
        site_id = RECORDED_ON[fixture]

        name = await catalog.organism_parameter(site_id, "transcript", search_name)

        assert name == marked
        discovery.get_search_details.assert_any_await(
            SearchContext(
                site_id=site_id, record_type="transcript", search_name=search_name
            )
        )

    async def test_a_search_with_no_mark_has_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fixture = "search_with_a_hidden_required_parameter"
        _discovery(monkeypatch, fixture)
        search_name = recorded_search(fixture).search_data.url_segment

        name = await catalog.organism_parameter("plasmodb", "transcript", search_name)

        assert name is None

    async def test_a_marked_tree_whose_leaves_name_no_organism_has_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mass_spec = _site_search("plasmodb_genes_by_mass_spec")
        _serving(monkeypatch, {"GenesByMassSpec": mass_spec})

        name = await catalog.organism_parameter(
            "plasmodb", "transcript", "GenesByMassSpec"
        )

        assert name is None

    async def test_the_organism_search_names_its_own_parameter(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _serving(monkeypatch, {})

        name = await catalog.organism_parameter(
            "plasmodb", "transcript", "GenesByTaxon"
        )

        assert name == "organism"

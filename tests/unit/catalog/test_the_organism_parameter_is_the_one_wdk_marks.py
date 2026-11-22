"""The organism parameter is the one WDK marks, or one whose leaves are the site's
organisms, whatever its name."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from tests._support.recorded_searches import recorded_search
from veupathdb.domain import SearchContext
from veupathdb.testing import NEEDS_QA_RECORDING, needs_qa_recording
from veupathdb.wdk import WDKParameter, WDKSearchResponse

from veupathdb_mcp import catalog
from veupathdb_mcp.catalog import organisms
from veupathdb_mcp.catalog.overview_formatting import format_search_overview
from veupathdb_mcp.catalog.param_formatting import format_param_info_typed
from veupathdb_mcp.catalog.param_sheet import build_sheet

MARKED = [
    ("search_genes_by_ngs_snps", "organismSinglePick"),
    ("search_genes_by_gene_model_chars", "organism_select_none"),
    ("search_genes_by_molecular_weight", "organism"),
    ("search_genes_by_taxon", "organism"),
    ("search_genes_by_location", "organismSinglePick"),
    ("search_genes_by_variant_characteristics", "organism_select_none"),
]
# The site each recorded search came from.
RECORDED_ON = {
    "search_genes_by_ngs_snps": "plasmodb",
    "search_genes_by_gene_model_chars": "vectorbase",
    "search_genes_by_molecular_weight": "plasmodb",
    "search_genes_by_taxon": "plasmodb",
    "search_genes_by_location": "plasmodb",
    "search_genes_by_variant_characteristics": "vectorbase",
}
_FIXTURES = Path(__file__).parent / "fixtures"
_SITE_LIST = _FIXTURES / "plasmodb_sequences_by_taxon.json"
_ALPHAFOLD = _FIXTURES / "plasmodb_genes_with_alphafold.json"
_MASS_SPEC = _FIXTURES / "plasmodb_genes_by_mass_spec.json"


def _site_search(path: Path) -> WDKSearchResponse:
    recorded = json.loads(path.read_text())
    return WDKSearchResponse.model_validate(recorded["response_json"])


def _serving(
    monkeypatch: pytest.MonkeyPatch, *responses: WDKSearchResponse
) -> MagicMock:
    """Each search's definition, and plasmodb's taxon search under its record type."""
    served = {r.search_data.url_segment: r for r in responses}
    served["SequencesByTaxon"] = _site_search(_SITE_LIST)

    async def _details(ctx: SearchContext) -> WDKSearchResponse:
        return served[ctx.search_name]

    listing = MagicMock()
    listing.find_record_type_for_search = MagicMock(return_value="genomic-sequence")
    discovery = MagicMock()
    discovery.get_search_details = AsyncMock(side_effect=_details)
    discovery.get_catalog = AsyncMock(return_value=listing)
    monkeypatch.setattr(organisms, "get_discovery_service", lambda: discovery)
    return discovery


def _without_organism_properties(parameter: WDKParameter) -> WDKParameter:
    properties = {
        k: v for k, v in parameter.properties.items() if k != "organismProperties"
    }
    return parameter.model_copy(update={"properties": properties})


async def _infos(
    monkeypatch: pytest.MonkeyPatch, fixture: str
) -> list[catalog.ParameterInfo]:
    _serving(monkeypatch)
    parameters = recorded_search(fixture).search_data.parameters or []
    organism = await catalog.organism_parameter_of(RECORDED_ON[fixture], parameters)
    return format_param_info_typed(parameters, organism=organism)


@pytest.mark.parametrize(("fixture", "marked"), MARKED)
async def test_only_the_marked_parameter_is_the_organism_parameter(
    monkeypatch: pytest.MonkeyPatch, fixture: str, marked: str
) -> None:
    if needs_qa_recording(f"wdk/{fixture}.json"):
        pytest.skip(NEEDS_QA_RECORDING)
    infos = await _infos(monkeypatch, fixture)

    assert [info.name for info in infos if info.organism_param] == [marked]


@pytest.mark.skipif(
    needs_qa_recording("wdk/search_genes_by_ngs_snps.json"), reason=NEEDS_QA_RECORDING
)
async def test_the_mark_travels_on_the_wire(monkeypatch: pytest.MonkeyPatch) -> None:
    by_name = {
        info.name: info
        for info in await _infos(monkeypatch, "search_genes_by_ngs_snps")
    }

    assert by_name["organismSinglePick"].model_dump(by_alias=True)["organismParam"]
    assert not by_name["snp_class"].model_dump(by_alias=True)["organismParam"]


@pytest.mark.parametrize(("fixture", "marked"), MARKED)
async def test_the_sheet_names_the_organism_parameter(
    monkeypatch: pytest.MonkeyPatch, fixture: str, marked: str
) -> None:
    if needs_qa_recording(f"wdk/{fixture}.json"):
        pytest.skip(NEEDS_QA_RECORDING)
    sheet = build_sheet(await _infos(monkeypatch, fixture), query="genes")

    assert [entry.name for entry in sheet if entry.organism_param] == [marked]


@pytest.mark.skipif(
    needs_qa_recording("wdk/search_genes_by_gene_model_chars.json"),
    reason=NEEDS_QA_RECORDING,
)
async def test_the_overview_names_the_organism_parameter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = recorded_search("search_genes_by_gene_model_chars")

    overview = format_search_overview(
        definition=response.search_data,
        record_type="transcript",
        infos=await _infos(monkeypatch, "search_genes_by_gene_model_chars"),
        query="genes",
    )

    entries = overview.required + overview.optional
    assert [entry.name for entry in entries if entry.organism_param] == [
        "organism_select_none"
    ]


class TestOrganismParameter:
    def test_a_host_reads_it_from_the_package(self) -> None:
        assert catalog.organism_parameter is organisms.organism_parameter
        assert catalog.organism_parameter_of is organisms.organism_parameter_of
        assert {"organism_parameter", "organism_parameter_of"} <= set(catalog.__all__)

    @pytest.mark.parametrize(("fixture", "marked"), MARKED)
    async def test_a_marked_parameter_is_named_from_its_own_declaration(
        self, monkeypatch: pytest.MonkeyPatch, fixture: str, marked: str
    ) -> None:
        if needs_qa_recording(f"wdk/{fixture}.json"):
            pytest.skip(NEEDS_QA_RECORDING)
        response = recorded_search(fixture)
        discovery = _serving(monkeypatch, response)
        search_name = response.search_data.url_segment
        site_id = RECORDED_ON[fixture]

        name = await catalog.organism_parameter(site_id, "transcript", search_name)

        assert name == marked
        discovery.get_search_details.assert_awaited_once_with(
            SearchContext(
                site_id=site_id, record_type="transcript", search_name=search_name
            )
        )

    @pytest.mark.skipif(
        needs_qa_recording("wdk/search_with_a_hidden_required_parameter.json"),
        reason=NEEDS_QA_RECORDING,
    )
    async def test_a_search_with_no_organism_list_has_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        response = recorded_search("search_with_a_hidden_required_parameter")
        _serving(monkeypatch, response)

        name = await catalog.organism_parameter(
            "plasmodb", "transcript", response.search_data.url_segment
        )

        assert name is None

    @pytest.mark.skipif(
        needs_qa_recording(_ALPHAFOLD, _SITE_LIST), reason=NEEDS_QA_RECORDING
    )
    async def test_a_tree_of_the_sites_organisms_is_the_organism_parameter(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        alphafold = _site_search(_ALPHAFOLD)
        _serving(monkeypatch, alphafold)

        name = await catalog.organism_parameter(
            "plasmodb", "transcript", "GenesWithAlphafold"
        )

        assert name == "organismsWithAlphafold"

    @pytest.mark.skipif(
        needs_qa_recording(_ALPHAFOLD, _SITE_LIST), reason=NEEDS_QA_RECORDING
    )
    async def test_the_sheet_of_a_tree_of_the_sites_organisms_names_it(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _serving(monkeypatch)
        parameters = _site_search(_ALPHAFOLD).search_data.parameters or []
        organism = await catalog.organism_parameter_of("plasmodb", parameters)

        infos = format_param_info_typed(parameters, organism=organism)

        assert [info.name for info in infos if info.organism_param] == [
            "organismsWithAlphafold"
        ]

    @pytest.mark.skipif(
        needs_qa_recording(_ALPHAFOLD, _SITE_LIST), reason=NEEDS_QA_RECORDING
    )
    async def test_organism_leaves_without_organism_properties_are_no_mark(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _serving(monkeypatch)
        parameters = [
            _without_organism_properties(p)
            for p in _site_search(_ALPHAFOLD).search_data.parameters or []
        ]

        assert await catalog.organism_parameter_of("plasmodb", parameters) is None

    @pytest.mark.skipif(
        needs_qa_recording(_MASS_SPEC, _SITE_LIST), reason=NEEDS_QA_RECORDING
    )
    async def test_a_tree_of_samples_under_organisms_has_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _serving(monkeypatch, _site_search(_MASS_SPEC))

        name = await catalog.organism_parameter(
            "plasmodb", "transcript", "GenesByMassSpec"
        )

        assert name is None

    @pytest.mark.skipif(
        needs_qa_recording(_MASS_SPEC, _SITE_LIST), reason=NEEDS_QA_RECORDING
    )
    async def test_the_sheet_of_a_tree_of_samples_names_no_organism_parameter(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _serving(monkeypatch)
        parameters = _site_search(_MASS_SPEC).search_data.parameters or []
        organism = await catalog.organism_parameter_of("plasmodb", parameters)

        infos = format_param_info_typed(parameters, organism=organism)

        assert [info.name for info in infos if info.organism_param] == []

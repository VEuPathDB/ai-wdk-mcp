"""A search one dataset names runs on the organisms of that dataset."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from veupathdb import JSONObject
from veupathdb.devtools.wdk_capture import WDKExchange
from veupathdb.wdk import WDKRecordType

from veupathdb_mcp import catalog
from veupathdb_mcp.catalog import discovery, searches
from veupathdb_mcp.catalog.catalog_metadata import (
    DATASET_REPORT_PATH,
    OntologyCategories,
    dataset_report_request,
    load_dataset_metadata,
)
from veupathdb_mcp.catalog.discovery import CatalogPolicy, SearchCatalog
from veupathdb_mcp.catalog.experiment_card import ExperimentCard

_FIXTURES = Path(__file__).parent / "fixtures"
_HOMINIS_OOCYSTS = "GenesByRNASeqchomTU502_Widmer_oocysts_ebi_rnaSeq_RSRCPercentile"
_BINDING_SITES = "GenesByBindingSiteFeature"


class _RecordedSite:
    """A client that answers the dataset report with a recorded body."""

    def __init__(self, recording: str) -> None:
        self.exchange = WDKExchange.model_validate_json(
            (_FIXTURES / recording).read_text()
        )

    async def post(self, path: str, *, json: JSONObject) -> JSONObject:
        assert (path, json) == (DATASET_REPORT_PATH, dataset_report_request())
        assert self.exchange.response_json is not None
        return self.exchange.response_json

    async def get_record_types(self, *, expanded: bool) -> list[WDKRecordType]:
        del expanded
        return []


async def _loaded(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, site_id: str
) -> SearchCatalog:
    """The site's catalog, built from its recorded dataset report alone."""
    site = _RecordedSite(f"{site_id}_all_datasets.json")
    cards = await load_dataset_metadata(site, site_id)

    async def _datasets(*_args: object) -> list[ExperimentCard]:
        return cards

    async def _ontology(*_args: object) -> OntologyCategories:
        return OntologyCategories({}, set(), {})

    def _index(_self: SearchCatalog) -> None:
        return None

    monkeypatch.setattr(discovery, "load_dataset_metadata", _datasets)
    monkeypatch.setattr(discovery, "load_ontology_categories", _ontology)
    monkeypatch.setattr(SearchCatalog, "_collect_semantic_index", _index)
    built = SearchCatalog(
        site_id, cache_dir=tmp_path, policy=CatalogPolicy(), spawn=asyncio.create_task
    )
    await built.load(site)
    return built


def test_the_recording_is_the_request_the_build_posts() -> None:
    recorded = WDKExchange.model_validate_json(
        (_FIXTURES / "cryptodb_all_datasets.json").read_text()
    )

    assert recorded.url == (
        f"https://cryptodb.org/cryptodb/service{DATASET_REPORT_PATH}"
    )
    assert recorded.request_json == dataset_report_request()


async def test_a_card_lists_its_organisms_apart() -> None:
    cards = await load_dataset_metadata(
        _RecordedSite("cryptodb_all_datasets.json"), "cryptodb"
    )
    by_id = {card.dataset_id: card for card in cards}

    assert by_id["DS_e2d612d987"].organisms == ("Cryptosporidium hominis TU502",)
    assert by_id["DS_815bd9f4dd"].organisms == (
        "Cryptosporidium serpentis 8845_47",
        "Cryptosporidium sp. 43IA8 isolate 43IA8",
    )


def test_a_card_with_no_organism_lists_none() -> None:
    card = ExperimentCard(
        site_id="plasmodb",
        dataset_id="DS_x",
        name="n",
        organism="",
        assay="a",
        record_url="u",
    )

    assert card.organisms == ()


class TestTheCatalogReadsTheDatasetASearchRunsOn:
    async def test_a_search_one_dataset_names_has_its_organism(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        cryptodb = await _loaded(monkeypatch, tmp_path, "cryptodb")

        assert cryptodb.dataset_organisms(_HOMINIS_OOCYSTS) == [
            "Cryptosporidium hominis TU502"
        ]

    async def test_a_dataset_of_several_organisms_gives_each(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        plasmodb = await _loaded(monkeypatch, tmp_path, "plasmodb")

        assert plasmodb.dataset_organisms(_BINDING_SITES) == [
            "Plasmodium berghei ANKA",
            "Plasmodium chabaudi chabaudi",
            "Plasmodium falciparum 3D7",
            "Plasmodium falciparum IT",
            "Plasmodium knowlesi strain H",
            "Plasmodium vivax P01",
            "Plasmodium yoelii yoelii 17X",
        ]

    @pytest.mark.parametrize(
        "search_name", ["GeneByLocusTag", "GenesBySingleCell", "GenesWithSignalPeptide"]
    )
    async def test_a_search_several_datasets_name_has_none(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, search_name: str
    ) -> None:
        cryptodb = await _loaded(monkeypatch, tmp_path, "cryptodb")

        assert cryptodb.dataset_organisms(search_name) == []

    async def test_a_search_no_dataset_names_has_none(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        cryptodb = await _loaded(monkeypatch, tmp_path, "cryptodb")

        assert cryptodb.dataset_organisms("GenesByText") == []


class TestDatasetOrganisms:
    def test_a_host_reads_it_from_the_package(self) -> None:
        assert catalog.dataset_organisms is searches.dataset_organisms
        assert "dataset_organisms" in catalog.__all__

    async def test_it_reads_the_catalog_of_the_site(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        cryptodb = await _loaded(monkeypatch, tmp_path, "cryptodb")
        asked: list[str] = []

        async def _catalog(site_id: str) -> SearchCatalog:
            asked.append(site_id)
            return cryptodb

        service = MagicMock()
        service.get_catalog = _catalog
        monkeypatch.setattr(searches, "get_discovery_service", lambda: service)

        organisms = await catalog.dataset_organisms("cryptodb", _HOMINIS_OOCYSTS)

        assert organisms == ["Cryptosporidium hominis TU502"]
        assert asked == ["cryptodb"]

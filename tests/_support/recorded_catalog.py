"""A site's catalog built from its recorded AllDatasets report alone."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from veupathdb import JSONObject
from veupathdb.devtools.wdk_capture import WDKExchange
from veupathdb.wdk import WDKRecordType

from veupathdb_mcp.catalog import discovery
from veupathdb_mcp.catalog.catalog_metadata import (
    DATASET_REPORT_PATH,
    OntologyCategories,
    dataset_report_request,
    load_dataset_metadata,
)
from veupathdb_mcp.catalog.discovery import CatalogPolicy, SearchCatalog
from veupathdb_mcp.catalog.experiment_card import ExperimentCard

CATALOG_FIXTURES = Path(__file__).parent.parent / "unit" / "catalog" / "fixtures"


class RecordedDatasetSite:
    """A client that answers the dataset report with a recorded body."""

    def __init__(self, recording: str) -> None:
        self.exchange = WDKExchange.model_validate_json(
            (CATALOG_FIXTURES / recording).read_text()
        )

    async def post(self, path: str, *, json: JSONObject) -> JSONObject:
        assert (path, json) == (DATASET_REPORT_PATH, dataset_report_request())
        assert self.exchange.response_json is not None
        return self.exchange.response_json

    async def get_record_types(self, *, expanded: bool) -> list[WDKRecordType]:
        del expanded
        return []


async def recorded_catalog(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, site_id: str
) -> SearchCatalog:
    """The site's catalog, built from its recorded dataset report alone."""
    site = RecordedDatasetSite(f"{site_id}_all_datasets.json")
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

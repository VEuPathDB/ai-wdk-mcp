"""Two images share the snapshot file, so a reader checks the format it reads."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from veupathdb.wdk import WDKRecordType, WDKSearch

from veupathdb_mcp.catalog import discovery, disk_cache
from veupathdb_mcp.catalog.catalog_metadata import OntologyCategories
from veupathdb_mcp.catalog.discovery import CatalogPolicy, SearchCatalog
from veupathdb_mcp.catalog.disk_cache import (
    SNAPSHOT_FORMAT_VERSION,
    CatalogSnapshot,
    save_catalog_cache,
    try_load_catalog_cache,
)
from veupathdb_mcp.catalog.experiment_card import ExperimentCard

_ON_DISK = {"transcript": [WDKSearch(url_segment="A", display_name="A")]}

_CARD = ExperimentCard(
    site_id="testdb",
    dataset_id="DS_00f985857c",
    name="Cytoadherent and wild-type P. knowlesi (experiment 2)",
    organism="Plasmodium knowlesi strain H",
    assay="RNASeq",
    attribution="Chuang et al. 2022",
    pmids=["36056126"],
    record_url="https://plasmodb.org/plasmo/app/record/dataset/DS_00f985857c",
)

# The file a format-1 build wrote: two maps keyed by dataset id, no cards.
_FORMAT_ONE = {
    "format_version": 1,
    "cached_at": 0.0,
    "record_types": [],
    "searches": {"transcript": [{"urlSegment": "A", "displayName": "A"}]},
    "dataset_summaries": {"DS_00f985857c": "RNA Seq transcriptome analysis"},
    "dataset_contacts": {"DS_00f985857c": "a data contact"},
    "search_categories": {},
    "search_category_labels": {},
    "available_categories": [],
}


def _snapshot() -> CatalogSnapshot:
    return CatalogSnapshot(
        record_types=[],
        searches=_ON_DISK,
        datasets=[_CARD],
        search_categories={},
        available_categories=[],
    )


class _EmptyClient:
    """A site whose catalog holds nothing, so a rebuild is visible."""

    async def get_record_types(self, *, expanded: bool) -> list[WDKRecordType]:
        del expanded
        return []


def _offline_catalog(monkeypatch: pytest.MonkeyPatch, cache_dir: Path) -> SearchCatalog:
    """A catalog that reads and writes ``cache_dir`` and reaches no service."""

    async def _datasets(*_args: object) -> list[ExperimentCard]:
        return [_CARD]

    async def _ontology(*_args: object) -> OntologyCategories:
        return OntologyCategories({}, set(), {})

    def _index(_self: SearchCatalog) -> None:
        return None

    monkeypatch.setattr(discovery, "load_dataset_metadata", _datasets)
    monkeypatch.setattr(discovery, "load_ontology_categories", _ontology)
    monkeypatch.setattr(SearchCatalog, "_collect_semantic_index", _index)
    return SearchCatalog(
        "testdb",
        cache_dir=cache_dir,
        policy=CatalogPolicy(),
        spawn=asyncio.create_task,
    )


def test_every_written_snapshot_names_its_format(tmp_path: Path) -> None:
    save_catalog_cache("testdb", _snapshot(), cache_dir=tmp_path)

    written = json.loads((tmp_path / "testdb.json").read_text())

    assert written["format_version"] == SNAPSHOT_FORMAT_VERSION


def test_a_snapshot_of_this_format_is_read(tmp_path: Path) -> None:
    save_catalog_cache("testdb", _snapshot(), cache_dir=tmp_path)

    restored = try_load_catalog_cache("testdb", cache_dir=tmp_path)

    assert restored is not None
    assert restored.format_version == SNAPSHOT_FORMAT_VERSION
    assert restored.searches == _ON_DISK


async def test_a_snapshot_of_this_format_is_served(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    save_catalog_cache("testdb", _snapshot(), cache_dir=tmp_path)
    catalog = _offline_catalog(monkeypatch, tmp_path)

    await catalog.load(_EmptyClient())

    assert catalog._searches == _ON_DISK


async def test_a_snapshot_of_another_format_is_refused_and_rebuilt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    save_catalog_cache("testdb", _snapshot(), cache_dir=tmp_path)
    catalog = _offline_catalog(monkeypatch, tmp_path)
    monkeypatch.setattr(
        disk_cache, "SNAPSHOT_FORMAT_VERSION", SNAPSHOT_FORMAT_VERSION + 1
    )

    await catalog.load(_EmptyClient())

    assert catalog._searches == {}
    assert json.loads((tmp_path / "testdb.json").read_text())["format_version"] == (
        SNAPSHOT_FORMAT_VERSION + 1
    )


async def test_a_snapshot_without_a_format_is_refused_and_rebuilt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    save_catalog_cache("testdb", _snapshot(), cache_dir=tmp_path)
    path = tmp_path / "testdb.json"
    written = json.loads(path.read_text())
    del written["format_version"]
    path.write_text(json.dumps(written))
    catalog = _offline_catalog(monkeypatch, tmp_path)

    await catalog.load(_EmptyClient())

    assert catalog._searches == {}
    assert json.loads(path.read_text())["format_version"] == SNAPSHOT_FORMAT_VERSION


def test_the_snapshot_holds_cards_from_format_two() -> None:
    assert SNAPSHOT_FORMAT_VERSION == 2


def test_a_snapshot_carries_its_cards(tmp_path: Path) -> None:
    save_catalog_cache("testdb", _snapshot(), cache_dir=tmp_path)

    restored = try_load_catalog_cache("testdb", cache_dir=tmp_path)
    written = json.loads((tmp_path / "testdb.json").read_text())

    assert restored is not None
    assert restored.datasets == [_CARD]
    assert "dataset_summaries" not in written
    assert "dataset_contacts" not in written


def test_a_format_one_snapshot_is_refused(tmp_path: Path) -> None:
    (tmp_path / "testdb.json").write_text(json.dumps(_FORMAT_ONE))

    assert try_load_catalog_cache("testdb", cache_dir=tmp_path) is None


async def test_a_format_one_snapshot_is_rebuilt_with_cards(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "testdb.json").write_text(json.dumps(_FORMAT_ONE))
    catalog = _offline_catalog(monkeypatch, tmp_path)

    await catalog.load(_EmptyClient())

    written = json.loads((tmp_path / "testdb.json").read_text())
    assert catalog._searches == {}
    assert catalog._datasets == [_CARD]
    assert written["format_version"] == 2
    assert [card["datasetId"] for card in written["datasets"]] == ["DS_00f985857c"]


async def test_a_served_snapshot_restores_its_cards(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    save_catalog_cache("testdb", _snapshot(), cache_dir=tmp_path)
    catalog = _offline_catalog(monkeypatch, tmp_path)

    await catalog.load(_EmptyClient())

    assert catalog._datasets == [_CARD]


def test_the_refusal_names_both_formats(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    save_catalog_cache("testdb", _snapshot(), cache_dir=tmp_path)
    monkeypatch.setattr(disk_cache, "SNAPSHOT_FORMAT_VERSION", 99)
    warnings: list[dict[str, object]] = []
    monkeypatch.setattr(
        disk_cache.logger,
        "warning",
        lambda _event, **fields: warnings.append(fields),
    )

    try_load_catalog_cache("testdb", cache_dir=tmp_path)

    assert warnings
    assert warnings[-1]["found"] == SNAPSHOT_FORMAT_VERSION
    assert warnings[-1]["expected"] == 99

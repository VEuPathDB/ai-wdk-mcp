"""The own-site search ranking reads its own site's index and no experiment index."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from veupathdb.wdk import WDKRecordType, WDKSearch

from veupathdb_mcp.catalog import searches
from veupathdb_mcp.catalog.discovery import CatalogPolicy
from veupathdb_mcp.catalog.discovery_service import DiscoveryService
from veupathdb_mcp.catalog.disk_cache import CatalogSnapshot, save_catalog_cache
from veupathdb_mcp.catalog.experiment_card import ExperimentCard
from veupathdb_mcp.catalog.models import SearchMatch
from veupathdb_mcp.embeddings.experiment_index import sync_experiments

pytestmark = pytest.mark.asyncio

_QUERY = "RNA-Seq sporozoite excystation time course"

_SEARCHES = [
    WDKSearch(
        url_segment="GenesByRNASeqpfal3D7_Excystation",
        display_name="Sporozoite excystation RNA-Seq",
        description="Transcript levels across a sporozoite excystation time course",
    ),
    WDKSearch(
        url_segment="GenesByMolecularWeight",
        display_name="Molecular Weight",
        description="predicted molecular weight of the protein",
    ),
    WDKSearch(
        url_segment="GenesByTimeCourse",
        display_name="Time course expression",
        description="genes whose expression changes across a time course",
    ),
]


def _card(site_id: str, dataset_id: str) -> ExperimentCard:
    return ExperimentCard(
        site_id=site_id,
        dataset_id=dataset_id,
        name=_QUERY,
        organism="Cryptosporidium parvum Iowa II",
        assay="RNASeq",
        record_url=f"https://{site_id}.org/app/record/dataset/{dataset_id}",
    )


async def _served_catalog(tmp_path: Path) -> DiscoveryService:
    """A discovery service holding plasmodb from a snapshot, its index synced."""
    save_catalog_cache(
        "plasmodb",
        CatalogSnapshot(
            record_types=[WDKRecordType(url_segment="transcript")],
            searches={"transcript": _SEARCHES},
            datasets=[],
            search_categories={},
            available_categories=[],
        ),
        tmp_path,
    )
    service = DiscoveryService(
        cache_dir=tmp_path,
        budget_bytes=1024 * 1024 * 1024,
        policy=CatalogPolicy(refresh=False, sync=True),
        spawn=asyncio.create_task,
    )
    catalog = await service.get_catalog("plasmodb")
    started = catalog._index_sync
    assert isinstance(started, asyncio.Task)
    await started
    return service


def _answer(matches: list[SearchMatch]) -> list[tuple[str, float, float | None]]:
    return [
        (match.name, match.relevance, match.semantic_similarity) for match in matches
    ]


async def test_the_own_site_answer_is_the_same_with_other_sites_indexed(
    patch_app_db_engine: None,
    embedding_index_cleaner: None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del patch_app_db_engine, embedding_index_cleaner
    service = await _served_catalog(tmp_path)

    async def no_site_search(*_args: object) -> None:
        return None

    monkeypatch.setattr(searches, "get_discovery_service", lambda: service)
    monkeypatch.setattr(searches, "apply_site_search_bonus", no_site_search)

    before = await searches.search_for_searches("plasmodb", "transcript", _QUERY)
    await sync_experiments("plasmodb", [_card("plasmodb", "DS_p1").index_entry()])
    await sync_experiments("cryptodb", [_card("cryptodb", "DS_c1").index_entry()])
    after = await searches.search_for_searches("plasmodb", "transcript", _QUERY)

    assert [name for name, _, _ in _answer(before)] == [
        "GenesByRNASeqpfal3D7_Excystation",
        "GenesByTimeCourse",
        "GenesByMolecularWeight",
    ]
    assert all(similarity is not None for _, _, similarity in _answer(before))
    assert _answer(after) == _answer(before)

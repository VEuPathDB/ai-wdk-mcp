"""The site catalog's index over the shared record manager."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from veupathdb.wdk.wdk_models import WDKSearch

from veupathdb_mcp.catalog.discovery import CatalogPolicy, SearchCatalog
from veupathdb_mcp.embeddings.fake import FakeEmbedder
from veupathdb_mcp.embeddings.record_manager import index_size
from veupathdb_mcp.embeddings.semantic_index import (
    SemanticSearchIndex,
    catalog_index_id,
    enriched_text_limit,
)

pytestmark = pytest.mark.asyncio


def _search(name: str, display: str, description: str = "") -> WDKSearch:
    return WDKSearch(
        url_segment=name,
        display_name=display,
        description=description,
    )


_SEARCHES = {
    "transcript": [
        _search("GenesByGoTerm", "Genes by GO term", "gene ontology annotation"),
        _search("GenesByText", "Genes by text search", "free text over gene records"),
    ],
    "genomic-sequence": [_search("SequencesByLength", "Sequences by length")],
}


def _collected(
    site_id: str, searches: dict[str, list[WDKSearch]]
) -> SemanticSearchIndex:
    """An index holding its entries and nothing written yet."""
    index = SemanticSearchIndex(site_id=site_id)
    index.collect(searches)
    return index


async def _finish_sync(catalog: SearchCatalog) -> None:
    """Wait for the sync the catalog started beside itself, if it started one."""
    started = catalog._index_sync
    if started is not None:
        assert isinstance(started, asyncio.Task)
        await started


@pytest.fixture
def db(
    patch_app_db_engine: None,
    embedding_index_cleaner: None,
) -> None:
    del patch_app_db_engine, embedding_index_cleaner


async def test_a_build_syncs_one_entry_per_search(db: None) -> None:
    del db
    index = _collected("testdb", _SEARCHES)
    report = await index.sync()
    assert report.added == 3
    assert report.embedded_texts == 3
    assert await index_size(catalog_index_id("testdb")) == 3


async def test_a_second_build_of_the_same_catalog_embeds_nothing(
    db: None,
    fake_embedder: FakeEmbedder,
) -> None:
    del db
    await _collected("testdb", _SEARCHES).sync()
    fake_embedder.calls.clear()
    report = await _collected("testdb", _SEARCHES).sync()
    assert report.reused == 3
    assert report.embedded_texts == 0
    assert fake_embedder.calls == []


async def test_a_collect_without_a_sync_writes_nothing(
    db: None,
    fake_embedder: FakeEmbedder,
) -> None:
    del db
    index = _collected("testdb", _SEARCHES)
    assert len(index.entries) == 3
    assert fake_embedder.calls == []
    assert await index_size(catalog_index_id("testdb")) == 0


async def test_a_query_answers_with_the_search_and_its_record_type(db: None) -> None:
    del db
    index = _collected("testdb", _SEARCHES)
    await index.sync()
    wanted = next(e for e in index.entries if e.search_name == "GenesByGoTerm")
    hits = await index.query(wanted.enriched_text, top_k=3)
    assert hits[0][0] == "GenesByGoTerm"
    assert hits[0][1] == "transcript"
    assert hits[0][2] == pytest.approx(1.0, abs=1e-6)
    assert {name for name, _, _ in hits} == {
        "GenesByGoTerm",
        "GenesByText",
        "SequencesByLength",
    }


async def test_a_query_on_another_site_reads_nothing(db: None) -> None:
    del db
    await _collected("testdb", _SEARCHES).sync()
    assert await SemanticSearchIndex(site_id="otherdb").query("anything") == []


async def test_the_enriched_text_is_cut_at_the_bound(db: None) -> None:
    del db
    index = _collected(
        "testdb", {"transcript": [_search("Long", "Long search", "d" * 9000)]}
    )
    assert len(index.entries[0].enriched_text) == enriched_text_limit()


async def test_an_empty_catalog_syncs_nothing(db: None) -> None:
    del db
    index = _collected("testdb", {})
    report = await index.sync()
    assert report.added == 0
    assert index.entries == []


def _catalog(site_id: str, *, sync: bool) -> SearchCatalog:
    """A catalog whose only host dependency this test drives is the sync policy."""
    return SearchCatalog(
        site_id,
        cache_dir=Path("/nonexistent"),
        policy=CatalogPolicy(sync=sync),
        spawn=asyncio.create_task,
    )


async def test_a_catalog_build_that_may_not_sync_writes_no_vector(
    db: None,
    fake_embedder: FakeEmbedder,
) -> None:
    """The gate lives on the catalog build, not only on the adapter."""
    del db
    catalog = _catalog("gateddb", sync=False)
    catalog._searches = _SEARCHES

    catalog._collect_semantic_index()
    await _finish_sync(catalog)

    assert await index_size(catalog_index_id("gateddb")) == 0
    assert fake_embedder.calls == []
    index = catalog.get_semantic_index()
    assert index is not None
    assert len(index.entries) == 3


async def test_a_catalog_build_that_may_sync_writes_its_vectors(
    db: None,
    fake_embedder: FakeEmbedder,
) -> None:
    del db
    catalog = _catalog("openeddb", sync=True)
    catalog._searches = _SEARCHES

    catalog._collect_semantic_index()
    await _finish_sync(catalog)

    assert await index_size(catalog_index_id("openeddb")) == 3
    assert fake_embedder.calls != []

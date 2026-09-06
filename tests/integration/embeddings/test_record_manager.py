"""The Postgres record manager: what it embeds, what it reuses, what it drops."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select, update

from veupathdb_mcp.embeddings.db import embedding_session
from veupathdb_mcp.embeddings.fake import FakeEmbedder
from veupathdb_mcp.embeddings.record_manager import (
    IndexEntry,
    prune_orphan_vectors,
    search_index,
    sync_index,
)
from veupathdb_mcp.embeddings.tables import (
    EmbeddingIndexEntry,
    EmbeddingVector,
)

_INDEX = "catalog:testdb"
_OTHER_INDEX = "catalog:otherdb"


@pytest.fixture
def embedder(
    patch_app_db_engine: None,
    embedding_index_cleaner: None,
    fake_embedder: FakeEmbedder,
) -> FakeEmbedder:
    del patch_app_db_engine, embedding_index_cleaner
    return fake_embedder


def _entries(*pairs: tuple[str, str]) -> list[IndexEntry]:
    return [IndexEntry(entry_id=entry_id, text=text) for entry_id, text in pairs]


async def _vector_rows() -> int:
    async with embedding_session() as session:
        return (
            await session.scalar(
                select(func.count()).select_from(EmbeddingVector),
            )
            or 0
        )


async def _membership(index_id: str) -> dict[str, str]:
    async with embedding_session() as session:
        rows = await session.execute(
            select(
                EmbeddingIndexEntry.entry_id,
                EmbeddingIndexEntry.content_hash,
            ).where(EmbeddingIndexEntry.index_id == index_id),
        )
        return {row.entry_id: row.content_hash for row in rows}


async def test_first_sync_embeds_every_entry(embedder: FakeEmbedder) -> None:
    report = await sync_index(_INDEX, _entries(("a", "alpha"), ("b", "beta")))
    assert report.added == 2
    assert report.updated == 0
    assert report.removed == 0
    assert report.reused == 0
    assert report.embedded_texts == 2
    assert await _vector_rows() == 2


async def test_identical_second_sync_embeds_nothing(embedder: FakeEmbedder) -> None:
    entries = _entries(("a", "alpha"), ("b", "beta"))
    await sync_index(_INDEX, entries)
    embedder.calls.clear()
    report = await sync_index(_INDEX, entries)
    assert report.reused == 2
    assert report.added == 0
    assert report.updated == 0
    assert report.embedded_texts == 0
    assert embedder.calls == []


async def test_a_changed_text_embeds_one(embedder: FakeEmbedder) -> None:
    await sync_index(_INDEX, _entries(("a", "alpha"), ("b", "beta")))
    embedder.calls.clear()
    report = await sync_index(_INDEX, _entries(("a", "alpha"), ("b", "beta two")))
    assert report.updated == 1
    assert report.reused == 1
    assert report.embedded_texts == 1
    assert embedder.calls == [["beta two"]]


async def test_a_removed_entry_leaves_the_membership(embedder: FakeEmbedder) -> None:
    del embedder
    await sync_index(_INDEX, _entries(("a", "alpha"), ("b", "beta")))
    report = await sync_index(_INDEX, _entries(("a", "alpha")))
    assert report.removed == 1
    assert set(await _membership(_INDEX)) == {"a"}


async def test_a_new_entry_embeds_one(embedder: FakeEmbedder) -> None:
    await sync_index(_INDEX, _entries(("a", "alpha")))
    embedder.calls.clear()
    report = await sync_index(_INDEX, _entries(("a", "alpha"), ("c", "gamma")))
    assert report.added == 1
    assert report.embedded_texts == 1
    assert embedder.calls == [["gamma"]]


async def test_two_indexes_share_one_vector_row(embedder: FakeEmbedder) -> None:
    await sync_index(_INDEX, _entries(("a", "alpha")))
    embedder.calls.clear()
    report = await sync_index(_OTHER_INDEX, _entries(("z", "alpha")))
    assert report.added == 1
    assert report.embedded_texts == 0
    assert embedder.calls == []
    assert await _vector_rows() == 1


async def test_search_ranks_the_identical_text_first(embedder: FakeEmbedder) -> None:
    del embedder
    await sync_index(
        _INDEX,
        _entries(("a", "alpha"), ("b", "beta"), ("c", "gamma")),
    )
    hits = await search_index(_INDEX, "beta", top_k=3)
    assert hits[0].entry_id == "b"
    assert {hit.entry_id for hit in hits} == {"a", "b", "c"}
    assert hits[0].similarity == pytest.approx(1.0, abs=1e-6)
    assert all(hit.similarity < 0.99 for hit in hits[1:])
    assert all(-1.0 <= hit.similarity <= 1.0 for hit in hits)


async def test_search_reads_only_its_own_index(embedder: FakeEmbedder) -> None:
    del embedder
    await sync_index(_INDEX, _entries(("a", "alpha")))
    await sync_index(_OTHER_INDEX, _entries(("z", "beta")))
    hits = await search_index(_OTHER_INDEX, "beta", top_k=5)
    assert [hit.entry_id for hit in hits] == ["z"]


async def test_search_on_an_empty_index_returns_nothing(
    embedder: FakeEmbedder,
) -> None:
    del embedder
    assert await search_index("catalog:absent", "anything", top_k=5) == []


async def test_prune_removes_only_old_orphans(embedder: FakeEmbedder) -> None:
    del embedder
    await sync_index(_INDEX, _entries(("a", "alpha"), ("b", "beta")))
    await sync_index(_INDEX, _entries(("a", "alpha")))
    async with embedding_session() as session:
        await session.execute(
            update(EmbeddingVector).values(
                created_at=datetime.now(UTC) - timedelta(days=30),
            ),
        )
        await session.commit()
    assert await prune_orphan_vectors(timedelta(days=7)) == 1
    assert await _vector_rows() == 1


async def test_prune_keeps_a_young_orphan(embedder: FakeEmbedder) -> None:
    del embedder
    await sync_index(_INDEX, _entries(("a", "alpha"), ("b", "beta")))
    await sync_index(_INDEX, _entries(("a", "alpha")))
    assert await prune_orphan_vectors(timedelta(days=7)) == 0
    assert await _vector_rows() == 2


async def test_similarity_is_the_cosine_and_not_a_distance(
    embedder: FakeEmbedder,
) -> None:
    """A non-identical pair pins the operator: L2 would give a different number."""
    await sync_index(_INDEX, _entries(("a", "alpha")))
    query_vector, text_vector = await embedder.embed_documents(["beta", "alpha"])
    expected = sum(q * t for q, t in zip(query_vector, text_vector, strict=True))

    hits = await search_index(_INDEX, "beta", top_k=1)

    assert hits[0].entry_id == "a"
    assert hits[0].similarity == pytest.approx(expected, abs=1e-6)
    # The pair is genuinely unlike, so 1.0 could not stand in for the cosine.
    assert abs(expected) < 0.5

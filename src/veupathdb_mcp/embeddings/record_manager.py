"""One index of embedded text, kept in Postgres and synced incrementally."""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from asyncpg.exceptions import PostgresError
from sqlalchemy import delete, func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from veupathdb import get_logger

from veupathdb_mcp.embeddings.db import embedding_session
from veupathdb_mcp.embeddings.embedder import get_embedder
from veupathdb_mcp.embeddings.errors import SemanticIndexUnavailableError
from veupathdb_mcp.embeddings.settings import get_embedding_settings
from veupathdb_mcp.embeddings.tables import (
    EmbeddingIndexEntry,
    EmbeddingVector,
)

logger = get_logger(__name__)

# Rows per statement. A driver binds one parameter per column per row, and a
# whole portal catalog in one statement would approach the protocol's limit.
_STATEMENT_ROWS = 500

_SEARCH_SQL = text(
    """
    SELECT e.entry_id AS entry_id,
           1 - (v.embedding <=> CAST(:query_vector AS vector)) AS similarity
    FROM embedding_index_entries AS e
    JOIN embedding_vectors AS v
      ON v.content_hash = e.content_hash AND v.model = :model
    WHERE e.index_id = :index_id
    ORDER BY v.embedding <=> CAST(:query_vector AS vector)
    LIMIT :top_k
    """,
)


@dataclass(frozen=True, slots=True)
class IndexEntry:
    """One member of an index: what it is called, and the text it is found by."""

    entry_id: str
    text: str


@dataclass(frozen=True, slots=True)
class SyncReport:
    """What one sync changed, and what it paid the API for."""

    added: int = 0
    updated: int = 0
    removed: int = 0
    reused: int = 0
    embedded_texts: int = 0


@dataclass(frozen=True, slots=True)
class IndexHit:
    """One ranked member, with its cosine similarity in [-1, 1]."""

    entry_id: str
    similarity: float


class IndexStoreUnavailableError(SemanticIndexUnavailableError):
    """The index's Postgres store did not answer this process."""


@asynccontextmanager
async def _index_session() -> AsyncIterator[AsyncSession]:
    """A session whose store failures reach the caller as one typed error.

    A driver refusal is a plain ``Exception`` with no relation to ``OSError``,
    so an untranslated one reaches whatever asked the index a question.
    """
    try:
        async with embedding_session() as session:
            yield session
    except (PostgresError, SQLAlchemyError, OSError) as exc:
        msg = f"the embedding index store did not answer: {type(exc).__name__}: {exc}"
        raise IndexStoreUnavailableError(msg) from exc


def content_hash(model: str, body: str) -> str:
    """Content address of a vector: the model and the text decide it."""
    return hashlib.sha256(f"{model}\n{body}".encode()).hexdigest()


async def sync_index(index_id: str, entries: Sequence[IndexEntry]) -> SyncReport:
    """Make the index hold exactly these entries, embedding only what is new."""
    settings = get_embedding_settings()
    model = settings.embedding_model
    limit = settings.embedding_input_char_limit
    bodies = {entry.entry_id: entry.text[:limit] for entry in entries}
    wanted = {entry_id: content_hash(model, body) for entry_id, body in bodies.items()}

    async with _index_session() as session:
        rows = await session.execute(
            select(
                EmbeddingIndexEntry.entry_id,
                EmbeddingIndexEntry.content_hash,
            ).where(EmbeddingIndexEntry.index_id == index_id),
        )
        current: dict[str, str] = {row.entry_id: row.content_hash for row in rows}
        added = len([entry_id for entry_id in wanted if entry_id not in current])
        reused = len(
            [
                entry_id
                for entry_id, digest in wanted.items()
                if current.get(entry_id) == digest
            ],
        )
        updated = len(wanted) - added - reused
        gone = [entry_id for entry_id in current if entry_id not in wanted]

        missing = await _missing_bodies(session, model, wanted, bodies)
        if missing:
            vectors = await get_embedder().embed_documents(list(missing.values()))
            vector_rows = [
                {"model": model, "content_hash": digest, "embedding": vector}
                for digest, vector in zip(missing, vectors, strict=True)
            ]
            for vector_chunk in _chunks(vector_rows):
                await session.execute(
                    insert(EmbeddingVector)
                    .values(vector_chunk)
                    .on_conflict_do_nothing(),
                )

        member_rows = [
            {"index_id": index_id, "entry_id": entry_id, "content_hash": digest}
            for entry_id, digest in wanted.items()
        ]
        for member_chunk in _chunks(member_rows):
            statement = insert(EmbeddingIndexEntry).values(member_chunk)
            await session.execute(
                statement.on_conflict_do_update(
                    index_elements=["index_id", "entry_id"],
                    set_={
                        "content_hash": statement.excluded.content_hash,
                        "updated_at": func.now(),
                    },
                ),
            )
        for gone_chunk in _chunks(gone):
            await session.execute(
                delete(EmbeddingIndexEntry).where(
                    EmbeddingIndexEntry.index_id == index_id,
                    EmbeddingIndexEntry.entry_id.in_(gone_chunk),
                ),
            )
        await session.commit()

    report = SyncReport(
        added=added,
        updated=updated,
        removed=len(gone),
        reused=reused,
        embedded_texts=len(missing),
    )
    logger.info(
        "Embedding index synced",
        index_id=index_id,
        added=report.added,
        updated=report.updated,
        removed=report.removed,
        reused=report.reused,
        embedded_texts=report.embedded_texts,
    )
    return report


async def _missing_bodies(
    session: AsyncSession,
    model: str,
    wanted: dict[str, str],
    bodies: dict[str, str],
) -> dict[str, str]:
    """The content hashes with no vector row yet, mapped to their text."""
    by_hash = {wanted[entry_id]: body for entry_id, body in bodies.items()}
    if not by_hash:
        return {}
    stored = set(
        (
            await session.execute(
                select(EmbeddingVector.content_hash).where(
                    EmbeddingVector.model == model,
                    EmbeddingVector.content_hash.in_(list(by_hash)),
                ),
            )
        )
        .scalars()
        .all(),
    )
    return {digest: body for digest, body in by_hash.items() if digest not in stored}


async def search_index(index_id: str, query: str, top_k: int) -> list[IndexHit]:
    """The index's members ranked by cosine similarity to the query."""
    settings = get_embedding_settings()
    vector = await get_embedder().embed_query(query)
    async with _index_session() as session:
        rows = await session.execute(
            _SEARCH_SQL,
            {
                "query_vector": _vector_literal(vector),
                "model": settings.embedding_model,
                "index_id": index_id,
                "top_k": top_k,
            },
        )
        return [
            IndexHit(entry_id=entry_id, similarity=float(similarity))
            for entry_id, similarity in rows.all()
        ]


async def index_size(index_id: str) -> int:
    """How many members the index holds."""
    async with _index_session() as session:
        return (
            await session.scalar(
                select(func.count())
                .select_from(EmbeddingIndexEntry)
                .where(EmbeddingIndexEntry.index_id == index_id),
            )
            or 0
        )


async def prune_orphan_vectors(older_than: timedelta) -> int:
    """Delete vectors no index names any more, once they are old enough."""
    cutoff = datetime.now(UTC) - older_than
    async with _index_session() as session:
        referenced = select(EmbeddingIndexEntry.content_hash).where(
            EmbeddingIndexEntry.content_hash == EmbeddingVector.content_hash,
        )
        orphans = (
            (
                await session.execute(
                    select(EmbeddingVector.content_hash).where(
                        EmbeddingVector.created_at < cutoff,
                        ~referenced.exists(),
                    ),
                )
            )
            .scalars()
            .all()
        )
        for orphan_chunk in _chunks(list(orphans)):
            await session.execute(
                delete(EmbeddingVector).where(
                    EmbeddingVector.content_hash.in_(orphan_chunk),
                ),
            )
        if orphans:
            await session.commit()
            logger.info("Pruned orphan embedding vectors", deleted=len(orphans))
        return len(orphans)


def _chunks[T](rows: Sequence[T]) -> list[Sequence[T]]:
    """The rows in statement-sized groups."""
    return [
        rows[start : start + _STATEMENT_ROWS]
        for start in range(0, len(rows), _STATEMENT_ROWS)
    ]


def _vector_literal(vector: Sequence[float]) -> str:
    """The pgvector text form the cast in the query reads."""
    return "[" + ",".join(repr(float(value)) for value in vector) + "]"

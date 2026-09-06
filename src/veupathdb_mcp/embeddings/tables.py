"""The two tables the embedding index owns, on a base of their own.

The index ships without the assistant runtime, so its rows map on a base no
other unit shares.
"""

from datetime import datetime

from pgvector.sqlalchemy import VECTOR
from sqlalchemy import DateTime, Index, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from veupathdb_mcp.embeddings.embedder import EMBEDDING_DIMENSIONS

CONTENT_HASH_LENGTH = 64
INDEX_ID_LENGTH = 128
ENTRY_ID_LENGTH = 256
EMBEDDING_MODEL_LENGTH = 64


class EmbeddingBase(DeclarativeBase):
    """The declarative base the embedding index maps its rows on."""


class EmbeddingVector(EmbeddingBase):
    """One vector, addressed by the model and the text that produced it.

    Two indexes that carry the same text share this row.
    """

    __tablename__ = "embedding_vectors"

    model: Mapped[str] = mapped_column(String(EMBEDDING_MODEL_LENGTH), primary_key=True)
    content_hash: Mapped[str] = mapped_column(
        String(CONTENT_HASH_LENGTH), primary_key=True
    )
    embedding: Mapped[list[float]] = mapped_column(
        VECTOR(EMBEDDING_DIMENSIONS), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class EmbeddingIndexEntry(EmbeddingBase):
    """One index's membership: which entry carries which content."""

    __tablename__ = "embedding_index_entries"

    index_id: Mapped[str] = mapped_column(String(INDEX_ID_LENGTH), primary_key=True)
    entry_id: Mapped[str] = mapped_column(String(ENTRY_ID_LENGTH), primary_key=True)
    content_hash: Mapped[str] = mapped_column(
        String(CONTENT_HASH_LENGTH), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (Index("ix_embedding_index_entries_index_id", "index_id"),)

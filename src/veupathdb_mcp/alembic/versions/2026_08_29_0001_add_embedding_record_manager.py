"""Hold every embedding in Postgres, addressed by the text that produced it.

Revision ID: 2026_08_29_0001
Revises:
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import VECTOR

revision: str = "2026_08_29_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_EMBEDDING_DIMENSIONS = 1024


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "embedding_vectors",
        sa.Column("model", sa.String(64), primary_key=True),
        sa.Column("content_hash", sa.String(64), primary_key=True),
        sa.Column("embedding", VECTOR(_EMBEDDING_DIMENSIONS), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_table(
        "embedding_index_entries",
        sa.Column("index_id", sa.String(128), primary_key=True),
        sa.Column("entry_id", sa.String(256), primary_key=True),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_embedding_index_entries_index_id",
        "embedding_index_entries",
        ["index_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_embedding_index_entries_index_id",
        table_name="embedding_index_entries",
    )
    op.drop_table("embedding_index_entries")
    op.drop_table("embedding_vectors")

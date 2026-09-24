"""Hold each site's dataset cards, so another site's card reads without its catalog.

Revision ID: 2026_09_24_0002
Revises: 2026_08_29_0001
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "2026_09_24_0002"
down_revision: str | Sequence[str] | None = "2026_08_29_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "experiment_cards",
        sa.Column("site_id", sa.String(64), primary_key=True),
        sa.Column("dataset_id", sa.String(64), primary_key=True),
        sa.Column("card", JSONB(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("experiment_cards")

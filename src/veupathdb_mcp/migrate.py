"""Bring the embedding index's tables to this distribution's head."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy.engine import Connection


def alembic_config() -> Config:
    """The chain that ships with this package."""
    config = Config()
    config.set_main_option(
        "script_location", str(Path(__file__).resolve().parent / "alembic")
    )
    return config


def upgrade_head(connection: Connection) -> None:
    """Run the chain on a connection the host already opened."""
    config = alembic_config()
    config.attributes["connection"] = connection
    command.upgrade(config, "head")


def main() -> None:
    """Run the chain on the database ``EmbeddingSettings`` names."""
    command.upgrade(alembic_config(), "head")


if __name__ == "__main__":
    main()

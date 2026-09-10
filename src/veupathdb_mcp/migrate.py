"""Bring the embedding index's tables to this distribution's head."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy.engine import Connection

__all__ = [
    "OWNED_TABLES",
    "VERSION_TABLE",
    "include_object",
    "upgrade_head",
]

# This distribution's chain shares a database with its host's. Each records its
# position in a version table of its own.
VERSION_TABLE = "alembic_version_veupathdb_mcp"

# The tables this distribution creates and migrates. A host owns every other
# table in the database.
OWNED_TABLES = (
    "embedding_vectors",
    "embedding_index_entries",
)


def include_object(
    object_: object,
    name: str | None,
    type_: str,
    reflected: object,
    compare_to: object,
) -> bool:
    """Keep the tables this distribution owns, so autogenerate ignores a host's."""
    if type_ != "table":
        return True
    return name in OWNED_TABLES


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

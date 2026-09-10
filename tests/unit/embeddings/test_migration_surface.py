"""The names the migration chain publishes: its version table and its tables."""

from __future__ import annotations

from pathlib import Path

import veupathdb_mcp
from veupathdb_mcp.embeddings.tables import EmbeddingBase
from veupathdb_mcp.migrate import OWNED_TABLES, VERSION_TABLE, include_object


def test_the_version_table_is_the_name_the_chain_stamps() -> None:
    assert VERSION_TABLE == "alembic_version_veupathdb_mcp"


def test_one_module_defines_the_version_table_name() -> None:
    """A host reads the name, so a second copy of it cannot exist here."""
    source = Path(str(veupathdb_mcp.__file__)).parent
    holders = sorted(
        path.relative_to(source).as_posix()
        for path in source.rglob("*.py")
        if VERSION_TABLE in path.read_text()
    )

    assert holders == ["migrate.py"]


def test_the_owned_tables_are_the_tables_the_index_maps() -> None:
    assert set(OWNED_TABLES) == set(EmbeddingBase.metadata.tables)


def test_the_owned_tables_are_the_two_index_tables() -> None:
    assert OWNED_TABLES == ("embedding_vectors", "embedding_index_entries")


def test_the_filter_keeps_every_table_this_distribution_owns() -> None:
    kept = [
        name for name in OWNED_TABLES if include_object(None, name, "table", True, None)
    ]

    assert kept == list(OWNED_TABLES)


def test_the_filter_drops_a_table_the_host_owns() -> None:
    assert include_object(None, "users", "table", True, None) is False
    assert include_object(None, "conversations", "table", True, None) is False


def test_the_filter_keeps_an_object_that_is_not_a_table() -> None:
    assert (
        include_object(None, "ix_embedding_index_entries_index_id", "index", True, None)
        is True
    )

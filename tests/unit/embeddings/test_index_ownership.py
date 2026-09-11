"""The embedding index owns its settings, its sessions and its two tables."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession

from veupathdb_mcp.embeddings import db
from veupathdb_mcp.embeddings.db import (
    embedding_session,
    use_embedding_session_factory,
)
from veupathdb_mcp.embeddings.settings import (
    EmbeddingSettings,
    get_embedding_settings,
)
from veupathdb_mcp.embeddings.tables import (
    EmbeddingBase,
    EmbeddingIndexEntry,
    EmbeddingVector,
)

INDEX_TABLES = {"embedding_vectors", "embedding_index_entries"}


def test_the_index_settings_keep_the_environment_variable_names() -> None:
    assert set(EmbeddingSettings.model_fields) == {
        "database_url",
        "embedding_backend",
        "embedding_batch_size",
        "embedding_input_char_limit",
        "embedding_model",
        "embedding_request_concurrency",
        "embedding_sql_echo",
        "openai_api_key",
    }


def test_the_index_settings_module_computes_no_path() -> None:
    spec = importlib.util.find_spec("veupathdb_mcp.embeddings.settings")
    assert spec is not None
    assert spec.origin is not None
    source = Path(spec.origin).read_text()

    assert "__file__" not in source
    assert "config.toml" not in source


def test_the_two_tables_map_on_the_index_base() -> None:
    assert set(EmbeddingBase.metadata.tables) == INDEX_TABLES
    assert EmbeddingVector.__tablename__ == "embedding_vectors"
    assert EmbeddingIndexEntry.__tablename__ == "embedding_index_entries"


def test_the_index_opens_the_session_the_host_installed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(db, "_source", db._SessionSource())
    handed: list[AsyncSession] = []

    def open_session() -> AsyncSession:
        session = AsyncSession()
        handed.append(session)
        return session

    use_embedding_session_factory(open_session)
    opened = embedding_session()

    assert handed == [opened]


def test_the_index_builds_its_own_engine_when_the_host_installs_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A standalone process reads the two tables through its own pool."""
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u@db.test/index")
    monkeypatch.setattr(db, "_source", db._SessionSource())
    monkeypatch.setattr(db, "_own", db._OwnFactory())

    opened = embedding_session()

    assert isinstance(opened, AsyncSession)
    assert opened.get_bind().url == make_url(get_embedding_settings().database_url)

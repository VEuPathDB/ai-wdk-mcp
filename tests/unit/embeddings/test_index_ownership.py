"""The embedding index owns its settings, its sessions and its three tables."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.pool import AsyncAdaptedQueuePool

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
    ExperimentCardRow,
)

INDEX_TABLES = {"embedding_vectors", "embedding_index_entries", "experiment_cards"}


def test_the_index_settings_keep_the_environment_variable_names() -> None:
    assert set(EmbeddingSettings.model_fields) == {
        "database_url",
        "embedding_backend",
        "embedding_batch_size",
        "embedding_db_max_overflow",
        "embedding_db_pool_size",
        "embedding_db_pool_timeout_seconds",
        "embedding_input_char_limit",
        "embedding_model",
        "embedding_request_concurrency",
        "embedding_sql_echo",
        "openai_api_key",
        "postgres_db",
        "postgres_host",
        "postgres_password",
        "postgres_port",
        "postgres_user",
    }


def test_the_index_settings_module_computes_no_path() -> None:
    spec = importlib.util.find_spec("veupathdb_mcp.embeddings.settings")
    assert spec is not None
    assert spec.origin is not None
    source = Path(spec.origin).read_text()

    assert "__file__" not in source
    assert "config.toml" not in source


def test_the_three_tables_map_on_the_index_base() -> None:
    assert set(EmbeddingBase.metadata.tables) == INDEX_TABLES
    assert EmbeddingVector.__tablename__ == "embedding_vectors"
    assert EmbeddingIndexEntry.__tablename__ == "embedding_index_entries"
    assert ExperimentCardRow.__tablename__ == "experiment_cards"


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
    """A standalone process reads its tables through its own pool."""
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u@db.test/index")
    monkeypatch.setattr(db, "_source", db._SessionSource())
    monkeypatch.setattr(db, "_own", db._OwnFactory())

    opened = embedding_session()

    assert isinstance(opened, AsyncSession)
    assert opened.get_bind().url == make_url(get_embedding_settings().database_url)


def _own_pool(monkeypatch: pytest.MonkeyPatch) -> AsyncAdaptedQueuePool:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u@db.test/index")
    monkeypatch.setattr(db, "_source", db._SessionSource())
    monkeypatch.setattr(db, "_own", db._OwnFactory())
    pool = embedding_session().get_bind().pool
    assert isinstance(pool, AsyncAdaptedQueuePool)
    return pool


def test_the_own_engine_keeps_a_small_pool_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = EmbeddingSettings()
    pool = _own_pool(monkeypatch)

    assert settings.embedding_db_max_overflow == 6
    assert pool.size() == 2
    assert pool.timeout() == pytest.approx(30.0)


def test_the_own_engine_uses_the_configured_pool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EMBEDDING_DB_POOL_SIZE", "4")
    monkeypatch.setenv("EMBEDDING_DB_MAX_OVERFLOW", "0")
    monkeypatch.setenv("EMBEDDING_DB_POOL_TIMEOUT_SECONDS", "7.5")

    pool = _own_pool(monkeypatch)

    assert pool.size() == 4
    assert pool.timeout() == pytest.approx(7.5)

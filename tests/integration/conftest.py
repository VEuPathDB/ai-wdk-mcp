"""A Postgres with pgvector, migrated by this package's own chain."""

from collections.abc import AsyncGenerator, Generator

import pytest
from sqlalchemy.engine import Connection, make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from testcontainers.community.postgres import PostgresContainer

from veupathdb_mcp.embeddings.db import use_embedding_session_factory
from veupathdb_mcp.migrate import upgrade_head

_IMAGE = "pgvector/pgvector:pg16"


@pytest.fixture(scope="session")
def database_url() -> Generator[str]:
    """A disposable Postgres, or the one ``DATABASE_URL`` names."""
    with PostgresContainer(_IMAGE, driver="asyncpg") as container:
        yield container.get_connection_url()


@pytest.fixture(scope="session")
async def index_engine(database_url: str) -> AsyncGenerator[AsyncEngine]:
    """The engine the index reads, with this package's chain at head."""
    engine = create_async_engine(make_url(database_url))
    async with engine.begin() as connection:
        await connection.run_sync(_migrate)
    try:
        yield engine
    finally:
        await engine.dispose()


def _migrate(connection: Connection) -> None:
    upgrade_head(connection)


@pytest.fixture
def patch_app_db_engine(index_engine: AsyncEngine) -> None:
    """The index opens its sessions on the test engine."""
    maker = async_sessionmaker(
        index_engine, class_=AsyncSession, expire_on_commit=False, autoflush=False
    )
    use_embedding_session_factory(maker)


@pytest.fixture
async def embedding_index_cleaner(index_engine: AsyncEngine) -> AsyncGenerator[None]:
    """Empty the shared vector store around a test that asserts on it."""
    await _truncate(index_engine)
    yield
    await _truncate(index_engine)


async def _truncate(index_engine: AsyncEngine) -> None:
    async with index_engine.begin() as connection:
        await connection.exec_driver_sql(
            "TRUNCATE TABLE embedding_index_entries, embedding_vectors",
        )

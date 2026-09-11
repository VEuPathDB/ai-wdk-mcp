"""The database sessions the embedding index opens, and where they come from."""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from veupathdb_mcp.embeddings.settings import get_embedding_settings

type EmbeddingSessionFactory = Callable[[], AsyncSession]


class _OwnFactory:
    """The session maker this process builds when the host installs none."""

    maker: async_sessionmaker[AsyncSession] | None = None


_own = _OwnFactory()


def _own_session() -> AsyncSession:
    """A session on the index's own engine, built on first use."""
    if _own.maker is None:
        settings = get_embedding_settings()
        _own.maker = async_sessionmaker(
            create_async_engine(
                settings.database_url,
                echo=settings.embedding_sql_echo,
                pool_pre_ping=True,
            ),
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )
    return _own.maker()


class _SessionSource:
    """Where the index opens sessions. The host may replace it once."""

    def __init__(self) -> None:
        self._open: EmbeddingSessionFactory = _own_session

    def use(self, open_session: EmbeddingSessionFactory) -> None:
        self._open = open_session

    def open(self) -> AsyncSession:
        return self._open()


_source = _SessionSource()


def use_embedding_session_factory(open_session: EmbeddingSessionFactory) -> None:
    """Open sessions on the host application's engine instead of an own one."""
    _source.use(open_session)


def embedding_session() -> AsyncSession:
    """A new session on the engine in force for this process."""
    return _source.open()

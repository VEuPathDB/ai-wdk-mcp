"""The settings the embedding index reads, and where it reads them from."""

from collections.abc import Callable
from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class EmbeddingSettings(BaseSettings):
    """What the index needs to embed text and to reach its tables.

    A host application extends this class with its own settings and installs
    the extended instance through ``use_embedding_settings_source``.
    """

    model_config = SettingsConfigDict(
        env_file_encoding="utf-8",
        case_sensitive=False,
        env_ignore_empty=True,
        extra="ignore",
    )

    database_url: str = Field(default="", repr=False)
    api_debug: bool = False

    openai_api_key: str = Field(default="", repr=False)

    # Which embedder the process builds. "fake" is deterministic and offline.
    embedding_backend: Literal["openai", "fake"] = "openai"
    embedding_model: str = "text-embedding-3-large"
    # Requests in flight at once, and the largest request the batcher builds.
    embedding_request_concurrency: int = Field(default=8, ge=1)
    embedding_batch_size: int = Field(default=256, ge=1)
    # Characters of one input the embedder reads. A longer text is cut.
    embedding_input_char_limit: int = Field(default=2000, ge=1)


@lru_cache
def _default_settings() -> EmbeddingSettings:
    return EmbeddingSettings()


class _SettingsSource:
    """Where the index reads its settings. The host may replace it once."""

    def __init__(self) -> None:
        self._read: Callable[[], EmbeddingSettings] = _default_settings

    def use(self, read: Callable[[], EmbeddingSettings]) -> None:
        self._read = read

    def read(self) -> EmbeddingSettings:
        return self._read()


_source = _SettingsSource()


def use_embedding_settings_source(read: Callable[[], EmbeddingSettings]) -> None:
    """Read settings from the host application instead of the environment."""
    _source.use(read)


def get_embedding_settings() -> EmbeddingSettings:
    """The settings in force for this process."""
    return _source.read()

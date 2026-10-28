"""The settings the MCP server reads, and where it reads them from."""

from collections.abc import Callable
from functools import cached_property, lru_cache
from pathlib import Path
from typing import Self

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from veupathdb_mcp.service_tokens import ServiceTokenRegistry

__all__ = [
    "McpSettings",
    "get_mcp_settings",
    "use_mcp_settings_source",
]

DEFAULT_CATALOG_CACHE_DIR = Path("data/catalogs")


class McpSettings(BaseSettings):
    """What the server needs to publish itself and to hold its catalogs.

    A host application extends this class with its own settings and installs
    the extended instance through ``use_mcp_settings_source``.
    """

    model_config = SettingsConfigDict(
        hide_input_in_errors=True,
        env_file_encoding="utf-8",
        case_sensitive=False,
        env_ignore_empty=True,
        extra="ignore",
        validate_by_name=True,
    )

    # The server's own public URL, and the applications it serves in service
    # mode. The secrets are separate from a host application's own service
    # tokens, because a credential sent to an MCP server must not authenticate
    # to an API.
    wdk_mcp_base_url: str = ""
    wdk_mcp_service_tokens: str = Field(default="", repr=False)

    # Accounted megabytes of per-site catalogs and semantic indexes one process
    # holds. The least recently used site leaves when the budget is reached.
    site_catalog_budget_mb: int = 512
    # Whether this process rebuilds a stale catalog. A process that only serves
    # reads the snapshot the refreshing process saved.
    catalog_refresh_enabled: bool = True
    # Whether this process syncs an embedding index. A process that only reads
    # searches what the syncing process wrote.
    embedding_index_sync_enabled: bool = True
    # Where per-site catalog snapshots are read and written. Two processes that
    # name the same directory exchange what one of them refreshes. A relative
    # path is read from the working directory, so a deployment states its own.
    catalog_cache_dir: Path = DEFAULT_CATALOG_CACHE_DIR
    search_line_pool_size: int = Field(default=1, ge=1)
    search_line_max_overflow: int = Field(default=1, ge=0)
    search_line_pool_timeout_seconds: float | None = Field(default=None, gt=0)
    # The key catalog reads ask the OpenAI Decisions API on. The server does
    # not start without it.
    openai_api_key: str = Field(default="", repr=False)
    decisions_timeout_seconds: float = Field(default=15.0, gt=0)
    # A vocabulary pick whose confidence is below this is not settled.
    decisions_vocab_min_confidence: float = Field(default=0.5, ge=0, le=1)

    @model_validator(mode="after")
    def _decisions_need_a_key(self) -> Self:
        if not self.openai_api_key.strip():
            msg = "OPENAI_API_KEY is not set. The Decisions API needs it."
            raise ValueError(msg)
        return self

    @cached_property
    def mcp_service_tokens(self) -> ServiceTokenRegistry:
        """The applications this server serves without a user."""
        return ServiceTokenRegistry.parse(self.wdk_mcp_service_tokens)


@lru_cache
def _default_settings() -> McpSettings:
    return McpSettings()


class _SettingsSource:
    """Where the server reads its settings. The host may replace it once."""

    def __init__(self) -> None:
        self._read: Callable[[], McpSettings] = _default_settings

    def use(self, read: Callable[[], McpSettings]) -> None:
        self._read = read

    def read(self) -> McpSettings:
        return self._read()


_source = _SettingsSource()


def use_mcp_settings_source(read: Callable[[], McpSettings]) -> None:
    """Read settings from the host application instead of the environment."""
    _source.use(read)


def get_mcp_settings() -> McpSettings:
    """The settings in force for this process."""
    return _source.read()

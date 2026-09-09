"""The settings the research MCP server reads, and where it reads them from."""

from collections.abc import Callable
from functools import cached_property, lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from veupathdb_mcp.service_tokens import ServiceTokenRegistry

DEFAULT_TIMEOUT_SECONDS = 15.0
DEFAULT_MAX_RETRIES = 3


class ResearchSettings(BaseSettings):
    """What the research server needs to publish itself and to reach its APIs.

    Every variable carries the ``RESEARCH_MCP_`` prefix, so this server shares
    no setting with the WDK server in the same distribution.
    """

    model_config = SettingsConfigDict(
        env_prefix="research_mcp_",
        env_file_encoding="utf-8",
        case_sensitive=False,
        env_ignore_empty=True,
        extra="ignore",
    )

    # The server's own public URL, and the applications it serves. This server
    # reads no account, so a service secret is the only credential it admits.
    base_url: str = ""
    service_tokens: str = Field(default="", repr=False)

    # One outbound call's budget, and how many times a client repeats a call
    # the upstream API rate-limited.
    timeout_seconds: float = Field(default=DEFAULT_TIMEOUT_SECONDS, gt=0)
    max_retries: int = Field(default=DEFAULT_MAX_RETRIES, ge=1)

    # Semantic Scholar raises the anonymous rate limit for a keyed caller.
    s2_api_key: str = Field(default="", repr=False)

    # Crossref routes a call that names a mailbox to its polite pool. An empty
    # value keeps the anonymous pool.
    crossref_mailto: str = ""

    @cached_property
    def research_service_tokens(self) -> ServiceTokenRegistry:
        """The applications this server serves."""
        return ServiceTokenRegistry.parse(self.service_tokens)


@lru_cache
def _default_settings() -> ResearchSettings:
    return ResearchSettings()


class _SettingsSource:
    """Where the server reads its settings. The host may replace it once."""

    def __init__(self) -> None:
        self._read: Callable[[], ResearchSettings] = _default_settings

    def use(self, read: Callable[[], ResearchSettings]) -> None:
        self._read = read

    def read(self) -> ResearchSettings:
        return self._read()


_source = _SettingsSource()


def use_research_settings_source(read: Callable[[], ResearchSettings]) -> None:
    """Read settings from the host application instead of the environment."""
    _source.use(read)


def get_research_settings() -> ResearchSettings:
    """The settings in force for this process."""
    return _source.read()

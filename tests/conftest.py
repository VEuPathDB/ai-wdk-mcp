"""The process-wide state a test must not inherit: settings sources and the embedder."""

import os
from collections.abc import Generator

import pytest
from veupathdb.settings import VEuPathDBSettings, use_veupathdb_settings_source
from veupathdb.wdk import auth_login
from veupathdb.wdk.site_router import load_sites_config

from veupathdb_mcp.embeddings import embedder
from veupathdb_mcp.embeddings.embedder import get_embedder
from veupathdb_mcp.embeddings.fake import FakeEmbedder
from veupathdb_mcp.embeddings.settings import (
    EmbeddingSettings,
    use_embedding_settings_source,
)
from veupathdb_mcp.settings import McpSettings, use_mcp_settings_source

# No test embeds against a paid API.
os.environ["EMBEDDING_BACKEND"] = "fake"


@pytest.fixture(autouse=True)
def _settings_read_the_environment() -> Generator[None]:
    """Every read builds a fresh instance, so a monkeypatched variable applies."""
    use_mcp_settings_source(McpSettings)
    use_embedding_settings_source(EmbeddingSettings)
    use_veupathdb_settings_source(VEuPathDBSettings)
    load_sites_config.cache_clear()
    auth_login._signing_keys.clear()
    yield
    auth_login._signing_keys.clear()
    load_sites_config.cache_clear()


@pytest.fixture
def fake_embedder() -> FakeEmbedder:
    """A fresh deterministic embedder, so one test never reads another's calls."""
    embedder._holder.instance = None
    built = get_embedder()
    assert isinstance(built, FakeEmbedder)
    return built

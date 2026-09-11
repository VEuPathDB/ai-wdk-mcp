"""The process-wide state a test must not inherit: settings sources and the embedder."""

import os
from collections.abc import Generator

import pytest
from veupathdb import VEuPathDBSettings, use_veupathdb_settings_source
from veupathdb.wdk import reset_site_router

from veupathdb_mcp.embeddings import embedder
from veupathdb_mcp.embeddings.embedder import get_embedder
from veupathdb_mcp.embeddings.fake import FakeEmbedder
from veupathdb_mcp.embeddings.settings import (
    EmbeddingSettings,
    use_embedding_settings_source,
)
from veupathdb_mcp.research.settings import (
    ResearchSettings,
    use_research_settings_source,
)
from veupathdb_mcp.settings import McpSettings, use_mcp_settings_source

# No test embeds against a paid API.
os.environ["EMBEDDING_BACKEND"] = "fake"


@pytest.fixture(autouse=True)
def _settings_read_the_environment() -> Generator[None]:
    """Every read builds a fresh instance, so a monkeypatched variable applies."""
    use_mcp_settings_source(McpSettings)
    use_research_settings_source(ResearchSettings)
    use_embedding_settings_source(EmbeddingSettings)
    use_veupathdb_settings_source(VEuPathDBSettings)
    reset_site_router()
    yield
    reset_site_router()


@pytest.fixture
def fake_embedder() -> FakeEmbedder:
    """A fresh deterministic embedder, so one test never reads another's calls."""
    embedder._holder.instance = None
    built = get_embedder()
    assert isinstance(built, FakeEmbedder)
    return built

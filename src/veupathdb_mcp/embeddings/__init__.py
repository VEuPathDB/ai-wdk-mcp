"""The embedding index: the embedder, the two tables, and the indexes on them."""

from veupathdb_mcp.embeddings.db import embedding_session, use_embedding_session_factory
from veupathdb_mcp.embeddings.embedder import (
    EMBEDDING_DIMENSIONS,
    Embedder,
    EmbeddingUnavailableError,
    get_embedder,
)
from veupathdb_mcp.embeddings.errors import SemanticIndexUnavailableError
from veupathdb_mcp.embeddings.fake import FakeEmbedder
from veupathdb_mcp.embeddings.openai_embedder import OpenAIEmbedder
from veupathdb_mcp.embeddings.record_manager import (
    IndexEntry,
    IndexHit,
    IndexStoreUnavailableError,
    SyncReport,
    content_hash,
    index_size,
    prune_orphan_vectors,
    search_index,
    sync_index,
)
from veupathdb_mcp.embeddings.semantic_index import (
    SearchIndexEntry,
    SemanticSearchIndex,
    catalog_index_id,
    strip_markup,
)
from veupathdb_mcp.embeddings.settings import (
    EmbeddingSettings,
    get_embedding_settings,
    use_embedding_settings_source,
)
from veupathdb_mcp.embeddings.study_index import (
    STUDY_INDEX_ID,
    search_study_index,
    study_index_is_built,
    sync_study_index,
)
from veupathdb_mcp.embeddings.tables import (
    EmbeddingBase,
    EmbeddingIndexEntry,
    EmbeddingVector,
)

__all__ = [
    "EMBEDDING_DIMENSIONS",
    "STUDY_INDEX_ID",
    "Embedder",
    "EmbeddingBase",
    "EmbeddingIndexEntry",
    "EmbeddingSettings",
    "EmbeddingUnavailableError",
    "EmbeddingVector",
    "FakeEmbedder",
    "IndexEntry",
    "IndexHit",
    "IndexStoreUnavailableError",
    "OpenAIEmbedder",
    "SearchIndexEntry",
    "SemanticIndexUnavailableError",
    "SemanticSearchIndex",
    "SyncReport",
    "catalog_index_id",
    "content_hash",
    "embedding_session",
    "get_embedder",
    "get_embedding_settings",
    "index_size",
    "prune_orphan_vectors",
    "search_index",
    "search_study_index",
    "strip_markup",
    "study_index_is_built",
    "sync_index",
    "sync_study_index",
    "use_embedding_session_factory",
    "use_embedding_settings_source",
]

"""The embedding call every index caller shares, and the process-wide instance."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from veupathdb_mcp.embeddings.errors import SemanticIndexUnavailableError
from veupathdb_mcp.embeddings.settings import get_embedding_settings

# The width of every vector this index stores. The API returns the width it
# is asked for, so nothing truncates and nothing renormalizes.
EMBEDDING_DIMENSIONS = 1024


class EmbeddingUnavailableError(SemanticIndexUnavailableError):
    """The embedding API did not answer, so the caller has no vector."""

    def __init__(self, *, batch_size: int, cause: str) -> None:
        self.batch_size = batch_size
        super().__init__(
            f"The embedding API refused a batch of {batch_size} inputs: {cause}",
        )


@runtime_checkable
class Embedder(Protocol):
    """What a caller needs from an embedding backend."""

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """One unit-normalized vector per text, in the order given."""
        ...

    async def embed_query(self, text: str) -> list[float]:
        """One unit-normalized vector for a query."""
        ...


class _EmbedderHolder:
    """The embedder this process built, if it has built one."""

    instance: Embedder | None = None


_holder = _EmbedderHolder()


def get_embedder() -> Embedder:
    """The embedder the settings name, built once per process."""
    if _holder.instance is not None:
        return _holder.instance
    settings = get_embedding_settings()
    if settings.embedding_backend == "fake":
        from veupathdb_mcp.embeddings.fake import (  # noqa: PLC0415
            FakeEmbedder,
        )

        _holder.instance = FakeEmbedder()
    else:
        from veupathdb_mcp.embeddings.openai_embedder import (  # noqa: PLC0415
            OpenAIEmbedder,
        )

        _holder.instance = OpenAIEmbedder(settings=settings)
    return _holder.instance

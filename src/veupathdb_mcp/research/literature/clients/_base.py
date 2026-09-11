"""Shared base for literature search API clients."""

import asyncio

from pydantic import JsonValue
from veupathdb import get_logger
from veupathdb.errors import ExternalServiceError
from veupathdb.model import CamelModel

from veupathdb_mcp.research.citations import (
    Citation,
    ensure_unique_citation_tags,
)
from veupathdb_mcp.research.literature.papers import ParsedPaper
from veupathdb_mcp.research.settings import (
    DEFAULT_MAX_RETRIES,
    DEFAULT_TIMEOUT_SECONDS,
)

logger = get_logger(__name__)

API_USER_AGENT = "veupathdb-research-mcp/1.0"

_DEFAULT_BACKOFF_BASE_S = 1.0


class SearchResponse(CamelModel):
    """Standard response from a literature search client."""

    query: str
    source: str
    results: list[ParsedPaper]
    citations: list[Citation]


class BaseClient:
    """Common initialisation for all literature API clients."""

    def __init__(
        self,
        *,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ) -> None:
        self._timeout = timeout_seconds
        self._max_retries = max_retries

    # -- Template helpers --------------------------------------------------

    def _build_results(
        self,
        raw_items: list[JsonValue],
        *,
        abstract_max_chars: int,
    ) -> tuple[list[ParsedPaper], list[Citation]]:
        """Parse each raw item into a paper and a citation."""
        results: list[ParsedPaper] = []
        citations: list[Citation] = []
        for raw in raw_items:
            pair = self._parse_item(raw, abstract_max_chars=abstract_max_chars)
            if pair is None:
                continue
            result, citation = pair
            results.append(result)
            citations.append(citation)
        return results, citations

    def _parse_item(
        self,
        raw: JsonValue,
        *,
        abstract_max_chars: int,
    ) -> tuple[ParsedPaper, Citation] | None:
        """Parse one raw API item. Subclasses must override.

        A None return skips the item.
        """
        raise NotImplementedError


class StandardClient(BaseClient):
    """Client with the standard fetch-parse-build search pattern.

    Retry with exponential backoff on rate limits is built in.
    """

    _source_name: str = ""
    _backoff_base_s: float = _DEFAULT_BACKOFF_BASE_S

    async def search(
        self, query: str, *, limit: int, abstract_max_chars: int
    ) -> SearchResponse:
        raw_items = await self._fetch_with_retry(query, limit=limit)
        results, citations = self._build_results(
            raw_items, abstract_max_chars=abstract_max_chars
        )
        return build_response(
            query=query,
            source=self._source_name,
            results=results,
            citations=citations,
        )

    async def _fetch_with_retry(self, query: str, *, limit: int) -> list[JsonValue]:
        """Fetch raw items, with retry on rate limits and transient errors."""
        last_exc: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                return await self._fetch_raw(query, limit=limit)
            except ExternalServiceError as exc:
                last_exc = exc
                if "429" in str(exc):
                    wait = self._backoff_base_s * (2**attempt)
                    logger.warning(
                        "%s 429, retrying",
                        self._source_name,
                        attempt=attempt + 1,
                        wait_s=wait,
                    )
                    await asyncio.sleep(wait)
                    continue
                raise
            except Exception as exc:
                last_exc = exc
                if attempt < self._max_retries - 1:
                    wait = self._backoff_base_s * (2**attempt)
                    logger.warning(
                        "%s request failed, retrying",
                        self._source_name,
                        attempt=attempt + 1,
                        wait_s=wait,
                        error=str(exc),
                    )
                    await asyncio.sleep(wait)
                    continue
                raise
        raise ExternalServiceError(self._source_name, str(last_exc))

    async def _fetch_raw(self, query: str, *, limit: int) -> list[JsonValue]:
        raise NotImplementedError


def build_response(
    *,
    query: str,
    source: str,
    results: list[ParsedPaper],
    citations: list[Citation],
) -> SearchResponse:
    """Build the standard client response, deduplicating citation tags."""
    ensure_unique_citation_tags(citations)
    return SearchResponse(
        query=query,
        source=source,
        results=results,
        citations=citations,
    )

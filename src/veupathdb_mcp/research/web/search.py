"""Web search over ``ddgs``, one engine at a time.

The server asks each engine in turn and keeps the first answer, so the
response names the engine that answered and every engine that refused.
"""

import asyncio

import httpx
from ddgs import DDGS
from ddgs.exceptions import DDGSException
from pydantic import BaseModel, ConfigDict
from veupathdb.errors import ExternalServiceError
from veupathdb.model import CamelModel

from veupathdb_mcp.research.citations import (
    Citation,
    _new_citation_id,
    _now_iso,
    ensure_unique_citation_tags,
)
from veupathdb_mcp.research.models import EngineAttempt, SearchDiagnostics
from veupathdb_mcp.research.settings import DEFAULT_TIMEOUT_SECONDS
from veupathdb_mcp.research.text import (
    BROWSER_USER_AGENT,
    fetch_page_summary,
)

_MIN_SNIPPET_LENGTH = 40

_SERVICE_NAME = "web search"

# The general web engines ddgs serves, in the order this server asks them.
TEXT_ENGINES: tuple[str, ...] = ("duckduckgo", "mojeek", "yahoo", "google", "brave")


class WebSearchResult(CamelModel):
    title: str = ""
    url: str | None = None
    snippet: str | None = None
    summary: str | None = None


class _DdgsRow(BaseModel):
    """One raw row from ddgs. The key that holds the link differs by engine."""

    model_config = ConfigDict(extra="ignore")

    title: str = ""
    href: str | None = None
    url: str | None = None
    body: str | None = None
    snippet: str | None = None

    def to_result(self) -> WebSearchResult:
        return WebSearchResult(
            title=self.title,
            url=self.href or self.url,
            snippet=self.body or self.snippet,
        )


class WebSearchResponse(CamelModel):
    query: str
    effective_query: str
    search_adjusted: bool
    search_diagnostics: SearchDiagnostics
    results: list[WebSearchResult]
    citations: list[Citation]
    error: str | None = None


def _refusal_detail(attempts: list[EngineAttempt]) -> str:
    """Name every engine that was asked and what it answered."""
    named = "; ".join(
        f"{attempt.engine}: {attempt.error or 'no results'}" for attempt in attempts
    )
    return f"every engine refused: {named}"


class WebSearchService:
    """Web search backed by the ``ddgs`` library."""

    def __init__(
        self,
        *,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._timeout = timeout_seconds

    async def search(
        self,
        query: str,
        limit: int = 5,
        *,
        include_summary: bool = False,
        summary_max_chars: int = 600,
    ) -> WebSearchResponse:
        q = (query or "").strip()
        if not q:
            return WebSearchResponse(
                query=q,
                effective_query=q,
                search_adjusted=False,
                search_diagnostics=SearchDiagnostics(),
                results=[],
                citations=[],
                error="query_required",
            )
        limit = max(1, min(int(limit or 5), 10))
        summary_max_chars = max(200, min(int(summary_max_chars or 600), 4000))

        results, diagnostics = await self._ddgs_search(q, limit=limit)
        needs_summary = [
            r
            for r in results
            if not r.snippet or len(r.snippet.strip()) < _MIN_SNIPPET_LENGTH
        ]
        if include_summary and needs_summary:
            async with httpx.AsyncClient(
                timeout=min(self._timeout, 15.0),
                headers={
                    "User-Agent": BROWSER_USER_AGENT,
                    "Accept": (
                        "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
                    ),
                    "Accept-Language": "en-US,en;q=0.9",
                },
            ) as client:
                summaries = await asyncio.gather(
                    *[
                        fetch_page_summary(
                            client,
                            r.url,
                            max_chars=summary_max_chars,
                        )
                        for r in needs_summary
                    ]
                )
            for r, summary in zip(needs_summary, summaries, strict=True):
                r.summary = summary
                if summary:
                    r.snippet = summary

        citations: list[Citation] = []
        for item in results:
            title = item.title or item.url or "Web result"
            snippet = item.summary or item.snippet
            citations.append(
                Citation(
                    id=_new_citation_id("web"),
                    source="web",
                    title=title,
                    url=item.url,
                    snippet=snippet,
                    accessed_at=_now_iso(),
                )
            )
        ensure_unique_citation_tags(citations)

        return WebSearchResponse(
            query=q,
            effective_query=q,
            search_adjusted=False,
            search_diagnostics=diagnostics,
            results=results,
            citations=citations,
        )

    async def _ddgs_search(
        self,
        q: str,
        *,
        limit: int,
    ) -> tuple[list[WebSearchResult], SearchDiagnostics]:
        """Ask each engine in turn and keep the first answer.

        A search no engine answers is a refusal, not an empty result.
        """
        attempts: list[EngineAttempt] = []
        for engine in TEXT_ENGINES:
            results, attempt = await self._ask_engine(q, limit=limit, engine=engine)
            attempts.append(attempt)
            if results:
                return results, SearchDiagnostics(backend=engine, engines=attempts)
        raise ExternalServiceError(_SERVICE_NAME, _refusal_detail(attempts))

    async def _ask_engine(
        self,
        q: str,
        *,
        limit: int,
        engine: str,
    ) -> tuple[list[WebSearchResult], EngineAttempt]:
        try:
            raw = await asyncio.to_thread(self._ddgs_text, q, limit, engine)
        except DDGSException as exc:
            return [], EngineAttempt(engine=engine, error=str(exc))
        results = [_DdgsRow.model_validate(item).to_result() for item in raw]
        return results, EngineAttempt(engine=engine, results=len(results))

    @staticmethod
    def _ddgs_text(q: str, limit: int, backend: str) -> list[dict[str, str]]:
        with DDGS() as client:
            return client.text(q, max_results=limit, backend=backend)

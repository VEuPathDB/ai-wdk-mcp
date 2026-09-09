"""Web search over ``ddgs``, which fails over across its search backends.

A backend that rate-limits one call is replaced by another, so a refusal from
one engine is not a refused search.
"""

import asyncio
from dataclasses import dataclass, field

import httpx
from ddgs import DDGS
from pydantic import Field
from veupathdb.errors import ExternalServiceError
from veupathdb.model import CamelModel

from veupathdb_mcp.research.citations import (
    Citation,
    _new_citation_id,
    _now_iso,
    ensure_unique_citation_tags,
)
from veupathdb_mcp.research.settings import DEFAULT_TIMEOUT_SECONDS
from veupathdb_mcp.research.text import (
    BROWSER_USER_AGENT,
    fetch_page_summary,
)

_MIN_SNIPPET_LENGTH = 40


class WebSearchResult(CamelModel):
    title: str = ""
    url: str | None = None
    snippet: str | None = None
    summary: str | None = None


class SearchDiagnostics(CamelModel):
    blocked: bool = False
    attempts: int = 0
    status_codes: list[int] = Field(default_factory=list)
    backend: str = ""


class WebSearchResponse(CamelModel):
    query: str
    effective_query: str
    search_adjusted: bool
    search_diagnostics: SearchDiagnostics
    results: list[WebSearchResult]
    citations: list[Citation]
    error: str | None = None


@dataclass
class _DiagnosticsTracker:
    blocked: bool = False
    attempts: int = 0
    status_codes: list[int] = field(default_factory=list)
    backend: str = ""

    def to_model(self) -> SearchDiagnostics:
        return SearchDiagnostics(
            blocked=self.blocked,
            attempts=self.attempts,
            status_codes=list(self.status_codes),
            backend=self.backend,
        )


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

        results, diag = await self._ddgs_search(q, limit=limit)
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

        error: str | None = None
        if not results and diag.blocked:
            error = "search_blocked"

        return WebSearchResponse(
            query=q,
            effective_query=q,
            search_adjusted=False,
            search_diagnostics=diag.to_model(),
            results=results,
            citations=citations,
            error=error,
        )

    async def _ddgs_search(
        self,
        q: str,
        *,
        limit: int,
    ) -> tuple[list[WebSearchResult], _DiagnosticsTracker]:
        diag = _DiagnosticsTracker(attempts=1)
        service_name = "web search"
        try:
            raw = await asyncio.to_thread(self._ddgs_text, q, limit)
        except Exception as exc:
            diag.blocked = True
            raise ExternalServiceError(service_name, str(exc)) from exc

        results = [
            WebSearchResult(
                title=item.get("title", ""),
                url=item.get("href") or item.get("url"),
                snippet=item.get("body") or item.get("snippet"),
            )
            for item in raw
        ]
        if not results:
            diag.blocked = True
        return results, diag

    @staticmethod
    def _ddgs_text(q: str, limit: int) -> list[dict[str, str]]:
        with DDGS() as client:
            return client.text(q, max_results=limit)

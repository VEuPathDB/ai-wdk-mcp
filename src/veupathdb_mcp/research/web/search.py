"""Web search: the Brave Search API when a key is set, then ``ddgs`` one engine at a time.

The server asks each engine in turn and keeps the first answer, so the
response names the engine that answered and every engine that refused.
"""

import asyncio
from decimal import Decimal

import httpx
from ddgs import DDGS
from ddgs.exceptions import DDGSException
from pydantic import BaseModel, ConfigDict, Field
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

# The keyed engine, asked before every scraped one.
BRAVE_API = "brave-api"
_BRAVE_URL = "https://api.search.brave.com/res/v1/web/search"


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


class _BraveRow(BaseModel):
    """One web result as the Brave Search API returns it."""

    model_config = ConfigDict(extra="ignore")

    title: str = ""
    url: str | None = None
    description: str | None = None

    def to_result(self) -> WebSearchResult:
        return WebSearchResult(title=self.title, url=self.url, snippet=self.description)


class _BraveWeb(BaseModel):
    model_config = ConfigDict(extra="ignore")

    results: list[_BraveRow] = Field(default_factory=list)


class _BraveResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    web: _BraveWeb = Field(default_factory=_BraveWeb)


class WebSearchResponse(CamelModel):
    query: str
    effective_query: str
    search_adjusted: bool
    search_diagnostics: SearchDiagnostics
    results: list[WebSearchResult]
    citations: list[Citation]
    # What the engine that answered charged for this call. Scraping is free.
    cost_usd: Decimal = Decimal(0)
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
        brave_api_key: str = "",
        brave_cost_usd: Decimal = Decimal(0),
    ) -> None:
        self._timeout = timeout_seconds
        self._brave_api_key = brave_api_key
        self._brave_cost_usd = brave_cost_usd

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

        results, diagnostics = await self._search_engines(q, limit=limit)
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
            cost_usd=(
                self._brave_cost_usd if diagnostics.backend == BRAVE_API else Decimal(0)
            ),
        )

    async def _search_engines(
        self,
        q: str,
        *,
        limit: int,
    ) -> tuple[list[WebSearchResult], SearchDiagnostics]:
        """Ask the keyed engine, then each scraped one, and keep the first answer.

        A search no engine answers is a refusal, not an empty result.
        """
        attempts: list[EngineAttempt] = []
        if self._brave_api_key:
            results, attempt = await self._ask_brave(q, limit=limit)
            attempts.append(attempt)
            if results:
                return results, SearchDiagnostics(backend=BRAVE_API, engines=attempts)
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

    async def _ask_brave(
        self,
        q: str,
        *,
        limit: int,
    ) -> tuple[list[WebSearchResult], EngineAttempt]:
        try:
            rows = await self._brave_rows(q, limit)
        except ExternalServiceError as exc:
            return [], EngineAttempt(engine=BRAVE_API, error=str(exc))
        results = [_BraveRow.model_validate(row).to_result() for row in rows]
        return results, EngineAttempt(engine=BRAVE_API, results=len(results))

    async def _brave_rows(self, q: str, limit: int) -> list[dict[str, str]]:
        headers = {
            "Accept": "application/json",
            "X-Subscription-Token": self._brave_api_key,
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(
                    _BRAVE_URL,
                    params={"q": q, "count": limit},
                    headers=headers,
                )
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise ExternalServiceError(
                _SERVICE_NAME,
                f"{BRAVE_API} {exc.response.status_code} {exc.response.reason_phrase}",
            ) from exc
        except httpx.HTTPError as exc:
            raise ExternalServiceError(_SERVICE_NAME, f"{BRAVE_API} {exc}") from exc
        parsed = _BraveResponse.model_validate(response.json())
        return [row.model_dump() for row in parsed.web.results]

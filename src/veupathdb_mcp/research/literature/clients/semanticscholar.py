"""Semantic Scholar API client."""

import httpx
from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError
from veupathdb.errors import ExternalServiceError

from veupathdb_mcp.research.citations import (
    Citation,
    _new_citation_id,
    _now_iso,
)
from veupathdb_mcp.research.literature.clients._base import (
    API_USER_AGENT,
    StandardClient,
)
from veupathdb_mcp.research.literature.papers import (
    ParsedPaper,
    SemanticScholarRawPaper,
)
from veupathdb_mcp.research.settings import get_research_settings
from veupathdb_mcp.research.text import truncate_text


class _S2Response(BaseModel):
    """Envelope for the Semantic Scholar ``/paper/search`` response."""

    model_config = ConfigDict(extra="ignore")
    data: list[JsonValue] = Field(default_factory=list)


class SemanticScholarClient(StandardClient):
    """Client for Semantic Scholar API."""

    _source_name = "semanticscholar"

    async def _fetch_raw(self, query: str, *, limit: int) -> list[JsonValue]:
        url = "https://api.semanticscholar.org/graph/v1/paper/search"
        params = {
            "query": query,
            "limit": str(limit),
            "fields": "title,year,authors,url,abstract,journal,externalIds",
        }
        headers: dict[str, str] = {"User-Agent": API_USER_AGENT}
        api_key = get_research_settings().s2_api_key
        if api_key:
            headers["x-api-key"] = api_key

        try:
            async with httpx.AsyncClient(
                timeout=self._timeout, headers=headers
            ) as client:
                resp = await client.get(url, params=params, follow_redirects=True)
                resp.raise_for_status()
                payload = resp.json()
        except httpx.HTTPError as exc:
            service = "Semantic Scholar"
            raise ExternalServiceError(service, str(exc)) from exc
        try:
            parsed = _S2Response.model_validate(payload)
            items = parsed.data
        except ValidationError, TypeError:
            items = []
        return list(items)

    def _parse_item(
        self, raw: JsonValue, *, abstract_max_chars: int
    ) -> tuple[ParsedPaper, Citation] | None:
        try:
            parsed = SemanticScholarRawPaper.model_validate(raw).to_parsed_paper()
        except ValidationError, TypeError:
            return None
        parsed.abstract = truncate_text(parsed.abstract, abstract_max_chars)
        parsed.snippet = parsed.abstract or parsed.journal_title

        citation = Citation(
            id=_new_citation_id("s2"),
            source="semanticscholar",
            title=parsed.title or (parsed.url or "Semantic Scholar result"),
            url=parsed.url,
            authors=parsed.authors or None,
            year=parsed.year,
            doi=parsed.doi,
            pmid=parsed.pmid,
            snippet=parsed.abstract or parsed.journal_title,
            accessed_at=_now_iso(),
        )
        return parsed, citation

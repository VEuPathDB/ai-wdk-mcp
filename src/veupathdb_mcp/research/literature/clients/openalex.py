"""OpenAlex API client."""

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
from veupathdb_mcp.research.literature.papers import OpenAlexRawWork, ParsedPaper
from veupathdb_mcp.research.text import truncate_text


class _OAResponse(BaseModel):
    """Envelope for the OpenAlex ``/works`` search response."""

    model_config = ConfigDict(extra="ignore")
    results: list[JsonValue] = Field(default_factory=list)


class OpenAlexClient(StandardClient):
    """Client for OpenAlex API."""

    _source_name = "openalex"

    async def _fetch_raw(self, query: str, *, limit: int) -> list[JsonValue]:
        url = "https://api.openalex.org/works"
        params = {"search": query, "per-page": str(limit)}
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout, headers={"User-Agent": API_USER_AGENT}
            ) as client:
                resp = await client.get(url, params=params, follow_redirects=True)
                resp.raise_for_status()
                payload = resp.json()
        except httpx.HTTPError as exc:
            service = "OpenAlex"
            raise ExternalServiceError(service, str(exc)) from exc
        try:
            parsed = _OAResponse.model_validate(payload)
            items = parsed.results
        except ValidationError, TypeError:
            items = []
        return list(items)

    def _parse_item(
        self, raw: JsonValue, *, abstract_max_chars: int
    ) -> tuple[ParsedPaper, Citation] | None:
        try:
            parsed = OpenAlexRawWork.model_validate(raw).to_parsed_paper()
        except ValidationError, TypeError:
            return None
        parsed.abstract = truncate_text(parsed.abstract, abstract_max_chars)
        parsed.snippet = parsed.abstract or parsed.journal_title

        citation = Citation(
            id=_new_citation_id("openalex"),
            source="openalex",
            title=parsed.title or (parsed.url or "OpenAlex result"),
            url=parsed.url,
            authors=parsed.authors or None,
            year=parsed.year,
            doi=parsed.doi,
            snippet=parsed.abstract or parsed.journal_title,
            accessed_at=_now_iso(),
        )
        return parsed, citation

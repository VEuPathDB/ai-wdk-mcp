"""Crossref API client."""

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
from veupathdb_mcp.research.literature.papers import CrossRefRawWork, ParsedPaper
from veupathdb_mcp.research.settings import get_research_settings


def _user_agent(mailbox: str) -> str:
    """The polite pool reads the mailbox out of the User-Agent."""
    return f"{API_USER_AGENT} (mailto:{mailbox})" if mailbox else API_USER_AGENT


class _CrossrefMessage(BaseModel):
    """Inner ``message`` envelope in a Crossref API response."""

    model_config = ConfigDict(extra="ignore")
    items: list[JsonValue] = Field(default_factory=list)


class _CrossrefResponse(BaseModel):
    """Top-level envelope for the Crossref ``/works`` response."""

    model_config = ConfigDict(extra="ignore")
    message: _CrossrefMessage = Field(default_factory=_CrossrefMessage)


class CrossrefClient(StandardClient):
    """Client for Crossref API."""

    _source_name = "crossref"

    async def _fetch_raw(self, query: str, *, limit: int) -> list[JsonValue]:
        url = "https://api.crossref.org/works"
        params = {"query": query, "rows": str(limit)}
        mailbox = get_research_settings().crossref_mailto.strip()
        headers = {"User-Agent": _user_agent(mailbox)}
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout, headers=headers
            ) as client:
                resp = await client.get(url, params=params, follow_redirects=True)
                resp.raise_for_status()
                payload = resp.json()
        except httpx.HTTPError as exc:
            service = "CrossRef"
            raise ExternalServiceError(service, str(exc)) from exc
        try:
            parsed = _CrossrefResponse.model_validate(payload)
            items = parsed.message.items
        except ValidationError, TypeError:
            items = []
        return list(items)

    def _parse_item(
        self, raw: JsonValue, *, abstract_max_chars: int
    ) -> tuple[ParsedPaper, Citation] | None:
        try:
            parsed = CrossRefRawWork.model_validate(raw).to_parsed_paper()
        except ValidationError, TypeError:
            return None

        citation = Citation(
            id=_new_citation_id("crossref"),
            source="crossref",
            title=parsed.title or (parsed.url or "Crossref result"),
            url=parsed.url,
            authors=parsed.authors or None,
            year=parsed.year,
            doi=parsed.doi,
            snippet=parsed.journal_title,
            accessed_at=_now_iso(),
        )
        return parsed, citation

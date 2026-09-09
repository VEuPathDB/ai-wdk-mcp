"""Europe PMC API client."""

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
from veupathdb_mcp.research.literature.papers import EuropePmcRawResult, ParsedPaper
from veupathdb_mcp.research.text import truncate_text


class _EpmcResultList(BaseModel):
    """Inner ``resultList`` envelope in an Europe PMC response."""

    model_config = ConfigDict(extra="ignore")
    result: list[JsonValue] = Field(default_factory=list)


class _EpmcResponse(BaseModel):
    """Top-level envelope for the Europe PMC search response."""

    model_config = ConfigDict(extra="ignore")
    result_list: _EpmcResultList = Field(default_factory=_EpmcResultList)


class EuropePmcClient(StandardClient):
    """Client for Europe PMC API."""

    _source_name = "europepmc"

    async def _fetch_raw(self, query: str, *, limit: int) -> list[JsonValue]:
        url = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
        params = {
            "query": query,
            "format": "json",
            "pageSize": str(limit),
            "resultType": "core",
        }
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout, headers={"User-Agent": API_USER_AGENT}
            ) as client:
                resp = await client.get(url, params=params, follow_redirects=True)
                resp.raise_for_status()
                payload = resp.json()
        except httpx.HTTPError as exc:
            service = "EuropePMC"
            raise ExternalServiceError(service, str(exc)) from exc
        try:
            parsed = _EpmcResponse.model_validate(payload)
            hits = parsed.result_list.result
        except ValidationError, TypeError:
            hits = []
        return list(hits)

    def _parse_item(
        self, raw: JsonValue, *, abstract_max_chars: int
    ) -> tuple[ParsedPaper, Citation] | None:
        try:
            parsed = EuropePmcRawResult.model_validate(raw).to_parsed_paper()
        except ValidationError, TypeError:
            return None
        parsed.abstract = truncate_text(parsed.abstract, abstract_max_chars)

        citation = Citation(
            id=_new_citation_id("epmc"),
            source="europepmc",
            title=parsed.title or (parsed.url or "Europe PMC result"),
            url=parsed.url,
            authors=parsed.authors or None,
            year=parsed.year,
            doi=parsed.doi,
            pmid=parsed.pmid,
            snippet=parsed.abstract or parsed.journal_title,
            accessed_at=_now_iso(),
        )
        return parsed, citation

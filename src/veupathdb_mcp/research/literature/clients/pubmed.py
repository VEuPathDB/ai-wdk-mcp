"""PubMed API client."""

import asyncio
import re

import httpx
from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError
from veupathdb.errors import ExternalServiceError
from veupathdb.logging import get_logger

from veupathdb_mcp.research.citations import (
    Citation,
    _new_citation_id,
    _now_iso,
)
from veupathdb_mcp.research.literature.clients._base import (
    API_USER_AGENT,
    BaseClient,
    SearchResponse,
    build_response,
)
from veupathdb_mcp.research.literature.papers import (
    ParsedPaper,
    PubMedRawArticle,
    _PubMedSummaryAuthor,
)
from veupathdb_mcp.research.text import strip_tags, truncate_text

logger = get_logger(__name__)

_BACKOFF_BASE_S = 1.0

# ── PubMed response envelope models ─────────────────────────────────


class _ESearchResult(BaseModel):
    """Inner ``esearchresult`` from PubMed esearch response."""

    model_config = ConfigDict(extra="ignore")
    idlist: list[str] = Field(default_factory=list)


class _ESearchResponse(BaseModel):
    """Top-level envelope for PubMed esearch response."""

    model_config = ConfigDict(extra="ignore")
    esearchresult: _ESearchResult = Field(default_factory=_ESearchResult)


class _ESummaryResponse(BaseModel):
    """Top-level envelope for PubMed esummary response."""

    model_config = ConfigDict(extra="ignore")
    result: dict[str, JsonValue] = Field(default_factory=dict)


class _PubMedSummaryEntry(BaseModel):
    """One article entry from the PubMed esummary ``result`` dict."""

    model_config = ConfigDict(extra="ignore")
    title: str = ""
    pubdate: str = ""
    fulljournalname: str | None = None
    authors: list[_PubMedSummaryAuthor] = Field(default_factory=list)


class PubmedClient(BaseClient):
    """Client for PubMed API.

    PubMed requires a multi-step fetch (esearch -> esummary -> optional
    efetch for abstracts), so it keeps a custom ``search`` method.
    Per-item parsing still goes through ``_parse_item`` / ``_build_results``.
    """

    _include_abstract: bool = False

    async def search(
        self,
        query: str,
        *,
        limit: int,
        include_abstract: bool,
        abstract_max_chars: int,
    ) -> SearchResponse:
        """Search PubMed with retry on 429."""
        last_exc: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                raw_items = await self._fetch_raw(
                    query,
                    limit=limit,
                    include_abstract=include_abstract,
                )
                break
            except ExternalServiceError as exc:
                last_exc = exc
                if "429" in str(exc):
                    wait = _BACKOFF_BASE_S * (2**attempt)
                    logger.warning(
                        "PubMed 429, retrying",
                        attempt=attempt + 1,
                        wait_s=wait,
                    )
                    await asyncio.sleep(wait)
                    continue
                raise
        else:
            service = "PubMed"
            raise ExternalServiceError(service, str(last_exc))

        if not raw_items:
            return build_response(
                query=query, source="pubmed", results=[], citations=[]
            )
        self._include_abstract = include_abstract
        results, citations = self._build_results(
            raw_items, abstract_max_chars=abstract_max_chars
        )
        return build_response(
            query=query, source="pubmed", results=results, citations=citations
        )

    # -- fetch -------------------------------------------------------------

    async def _fetch_raw(
        self, query: str, *, limit: int, include_abstract: bool
    ) -> list[JsonValue]:
        """esearch + esummary (+ optional efetch) -> list of flat per-PMID dicts."""
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout, headers={"User-Agent": API_USER_AGENT}
            ) as client:
                esearch = await client.get(
                    "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
                    params={
                        "db": "pubmed",
                        "term": query,
                        "retmax": str(limit),
                        "retmode": "json",
                    },
                )
                esearch.raise_for_status()
                search_resp = _ESearchResponse.model_validate(esearch.json())
                pmids = [s for s in search_resp.esearchresult.idlist if s.strip()]
                if not pmids:
                    return []

                esummary = await client.get(
                    "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi",
                    params={"db": "pubmed", "id": ",".join(pmids), "retmode": "json"},
                )
                esummary.raise_for_status()
                sum_resp = _ESummaryResponse.model_validate(esummary.json())

                abstracts_by_pmid: dict[str, str] = {}
                if include_abstract:
                    efetch = await client.get(
                        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
                        params={
                            "db": "pubmed",
                            "id": ",".join(pmids),
                            "retmode": "xml",
                        },
                    )
                    efetch.raise_for_status()
                    xml = efetch.text or ""
                    for pmid in pmids:
                        m = re.search(
                            rf"<PMID>{re.escape(pmid)}</PMID>.*?<Abstract>.*?<AbstractText[^>]*>(.*?)</AbstractText>",
                            xml,
                            flags=re.IGNORECASE | re.DOTALL,
                        )
                        if m:
                            abstracts_by_pmid[pmid] = strip_tags(m.group(1))
        except httpx.HTTPError as exc:
            service = "PubMed"
            raise ExternalServiceError(service, str(exc)) from exc

        items: list[JsonValue] = []
        for pmid in pmids:
            try:
                entry = _PubMedSummaryEntry.model_validate(sum_resp.result.get(pmid))
            except ValidationError, TypeError:
                continue
            items.append(
                {
                    "pmid": pmid,
                    "title": entry.title,
                    "pubdate": entry.pubdate,
                    "journal": entry.fulljournalname,
                    "authors": [a.name for a in entry.authors if a.name],
                    "abstract": abstracts_by_pmid.get(pmid),
                }
            )
        return items

    # -- parse -------------------------------------------------------------

    def _parse_item(
        self, raw: JsonValue, *, abstract_max_chars: int
    ) -> tuple[ParsedPaper, Citation] | None:
        try:
            article = PubMedRawArticle.model_validate(raw)
        except ValidationError, TypeError:
            return None
        parsed = article.to_parsed_paper()

        abstract = (
            truncate_text(article.abstract, abstract_max_chars)
            if self._include_abstract
            else None
        )
        parsed.abstract = abstract
        parsed.snippet = abstract or parsed.journal_title

        citation = Citation(
            id=_new_citation_id("pubmed"),
            source="pubmed",
            title=parsed.title or parsed.url or "PubMed result",
            url=parsed.url,
            authors=parsed.authors or None,
            year=parsed.year,
            pmid=parsed.pmid,
            snippet=abstract or parsed.journal_title,
            accessed_at=_now_iso(),
        )
        return parsed, citation

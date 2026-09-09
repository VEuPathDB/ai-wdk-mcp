"""Raw paper models for each literature API, and the shared ``ParsedPaper``
normal form they all convert to.
"""

from __future__ import annotations

import contextlib
import re

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from veupathdb.model import CamelModel


class ParsedPaper(CamelModel):
    """Normalized paper representation shared across all literature clients."""

    model_config = ConfigDict(extra="ignore")

    title: str = ""
    year: int | None = None
    doi: str | None = None
    pmid: str | None = None
    url: str | None = None
    authors: list[str] = Field(default_factory=list)
    journal_title: str | None = None
    abstract: str | None = None
    snippet: str | None = None


# Semantic Scholar


class _S2Author(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str = ""


class _S2Journal(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str = ""


class _S2ExternalIds(BaseModel):
    model_config = ConfigDict(extra="ignore")
    doi: str | None = Field(None, alias="DOI")
    pub_med: str | None = Field(None, alias="PubMed")


class SemanticScholarRawPaper(BaseModel):
    """Raw paper from the Semantic Scholar API."""

    model_config = ConfigDict(extra="ignore")

    title: str = ""
    year: int | None = None
    url: str | None = None
    abstract: str | None = None
    authors: list[_S2Author] = Field(default_factory=list)
    journal: _S2Journal | None = None
    external_ids: _S2ExternalIds | None = Field(None)

    def to_parsed_paper(self) -> ParsedPaper:
        title = (self.title or "").strip()
        doi = self.external_ids.doi if self.external_ids else None
        pmid = self.external_ids.pub_med if self.external_ids else None
        journal_name = self.journal.name if self.journal and self.journal.name else None
        result_url = self.url or (f"https://doi.org/{doi}" if doi else None)
        author_names = [a.name for a in self.authors if a.name]
        return ParsedPaper(
            title=title,
            year=self.year,
            doi=doi,
            pmid=pmid,
            url=result_url,
            authors=author_names,
            journal_title=journal_name,
            abstract=self.abstract,
            snippet=self.abstract or journal_name,
        )


# OpenAlex


class _OAAuthorInfo(BaseModel):
    model_config = ConfigDict(extra="ignore")
    display_name: str = ""


class _OAAuthorship(BaseModel):
    model_config = ConfigDict(extra="ignore")
    author: _OAAuthorInfo = Field(default_factory=_OAAuthorInfo)


class _OAHostVenue(BaseModel):
    model_config = ConfigDict(extra="ignore")
    display_name: str = ""


class OpenAlexRawWork(BaseModel):
    """Raw work from the OpenAlex API.

    The abstract arrives as an inverted index, not as text.
    """

    model_config = ConfigDict(extra="ignore")

    title: str = ""
    publication_year: int | None = None
    doi: str | None = None
    id: str | None = None
    authorships: list[_OAAuthorship] = Field(default_factory=list)
    host_venue: _OAHostVenue | None = None
    abstract_inverted_index: dict[str, list[int]] | None = None

    @field_validator("doi", mode="after")
    @classmethod
    def _strip_doi_prefix(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return v.removeprefix("https://doi.org/")

    def _reconstruct_abstract(self) -> str | None:
        inv = self.abstract_inverted_index
        if not inv:
            return None
        pairs: list[tuple[int, str]] = [
            (i, word) for word, idxs in inv.items() for i in idxs
        ]
        if not pairs:
            return None
        pairs.sort(key=lambda x: x[0])
        return " ".join(w for _, w in pairs)

    def to_parsed_paper(self) -> ParsedPaper:
        title = (self.title or "").strip()
        result_url = f"https://doi.org/{self.doi}" if self.doi else self.id
        author_names = [
            a.author.display_name for a in self.authorships if a.author.display_name
        ]
        journal_name = (
            self.host_venue.display_name.strip()
            if self.host_venue and self.host_venue.display_name
            else None
        )
        abstract = self._reconstruct_abstract()
        return ParsedPaper(
            title=title,
            year=self.publication_year,
            doi=self.doi,
            url=result_url,
            authors=author_names,
            journal_title=journal_name,
            abstract=abstract,
            snippet=abstract or journal_name,
        )


# CrossRef


class _CRAuthor(BaseModel):
    model_config = ConfigDict(extra="ignore")
    given: str | None = None
    family: str | None = None

    @property
    def full_name(self) -> str | None:
        if self.family and self.given:
            return f"{self.given} {self.family}"
        return self.family


class _CRDateParts(BaseModel):
    """CrossRef date structure: ``{"date-parts": [[2021, 3, 15]]}``."""

    model_config = ConfigDict(extra="ignore")
    date_parts: list[list[int]] = Field(default_factory=list, alias="date-parts")

    @property
    def year(self) -> int | None:
        if self.date_parts and self.date_parts[0]:
            return self.date_parts[0][0]
        return None


class CrossRefRawWork(BaseModel):
    """Raw work from the CrossRef API."""

    model_config = ConfigDict(extra="ignore")

    title: list[str] = Field(default_factory=list)
    doi: str | None = Field(None, alias="DOI")
    url: str | None = Field(None, alias="URL")
    author: list[_CRAuthor] = Field(default_factory=list)
    container_title: list[str] = Field(default_factory=list, alias="container-title")
    published_print: _CRDateParts | None = Field(None, alias="published-print")
    published_online: _CRDateParts | None = Field(None, alias="published-online")

    def to_parsed_paper(self) -> ParsedPaper:
        title = self.title[0].strip() if self.title else ""
        journal = self.container_title[0].strip() if self.container_title else None
        date_source = self.published_print or self.published_online
        year = date_source.year if date_source else None
        result_url = self.url or (f"https://doi.org/{self.doi}" if self.doi else None)
        author_names = [a.full_name for a in self.author if a.full_name]
        return ParsedPaper(
            title=title,
            year=year,
            doi=self.doi,
            url=result_url,
            authors=author_names,
            journal_title=journal,
            snippet=journal,
        )


# Europe PMC


class EuropePmcRawResult(BaseModel):
    """Raw result from the Europe PMC API.

    ``pubYear`` arrives as a string and can hold a range such as
    ``"2020-2021"``, which has no single year.
    """

    model_config = ConfigDict(extra="ignore", coerce_numbers_to_str=False)

    title: str = ""
    pub_year: int | None = Field(None)
    doi: str | None = None
    pmid: str | None = None
    author_string: str | None = Field(None)
    journal_title: str | None = Field(None)
    abstract_text: str | None = Field(None)

    def to_parsed_paper(self) -> ParsedPaper:
        title = (self.title or "").strip()
        link: str | None = None
        if self.doi:
            link = f"https://doi.org/{self.doi}"
        elif self.pmid:
            link = f"https://pubmed.ncbi.nlm.nih.gov/{self.pmid}/"

        authors: list[str] = []
        if self.author_string:
            authors = [a.strip() for a in self.author_string.split(",") if a.strip()]

        jt = self.journal_title.strip() if self.journal_title else None

        return ParsedPaper(
            title=title,
            year=self.pub_year,
            doi=self.doi,
            pmid=self.pmid,
            url=link,
            authors=authors,
            journal_title=jt,
            abstract=self.abstract_text,
            snippet=jt,
        )


# PubMed


class _PubMedSummaryAuthor(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str = ""

    @model_validator(mode="before")
    @classmethod
    def _coerce_str(cls, data: object) -> object:
        """A PubMed summary author list holds plain strings."""
        if isinstance(data, str):
            return {"name": data}
        return data


class PubMedRawArticle(BaseModel):
    """Raw article assembled from the PubMed esummary and efetch responses."""

    model_config = ConfigDict(extra="ignore")

    pmid: str
    title: str = ""
    pubdate: str = ""
    authors: list[str] = Field(default_factory=list)
    journal: str | None = None
    abstract: str | None = None

    def to_parsed_paper(self) -> ParsedPaper:
        year: int | None = None
        m = re.search(r"(\d{4})", self.pubdate)
        if m:
            with contextlib.suppress(ValueError):
                year = int(m.group(1))
        url = f"https://pubmed.ncbi.nlm.nih.gov/{self.pmid}/"
        return ParsedPaper(
            title=self.title.strip(),
            year=year,
            pmid=self.pmid,
            url=url,
            authors=self.authors,
            journal_title=self.journal,
            snippet=self.journal,
        )


# arXiv


class ArxivRawEntry(BaseModel):
    """Raw arXiv entry. The arXiv API returns XML, not JSON."""

    model_config = ConfigDict(extra="ignore")
    xml: str = Field(alias="_xml")


class PreprintRawResult(BaseModel):
    """Raw preprint result from DuckDuckGo HTML scraping."""

    model_config = ConfigDict(extra="ignore")
    title: str = Field(alias="_title", default="")
    url: str | None = Field(alias="_url", default=None)

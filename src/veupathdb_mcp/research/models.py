"""What the two served research tools hand back to a model."""

from __future__ import annotations

from pydantic import ConfigDict, Field
from veupathdb.model import CamelModel


class SourceRef(CamelModel):
    """One citable source behind a result, addressable by its url."""

    id: str
    url: str
    title: str = ""


class WebResultOut(CamelModel):
    """One web result, as the model reads it."""

    title: str
    url: str | None = None
    snippet: str = ""


class EngineAttempt(CamelModel):
    """What one search engine did for one query."""

    model_config = ConfigDict(frozen=True)

    engine: str
    results: int = 0
    error: str | None = None


class SearchDiagnostics(CamelModel):
    """The engines one web search asked, in order, and the one that answered."""

    backend: str = ""
    engines: list[EngineAttempt] = Field(default_factory=list)


class WebSearchOut(CamelModel):
    """Ranked web results. The leading ones carry the page text."""

    query: str
    results: list[WebResultOut] = Field(default_factory=list)
    sources: list[SourceRef] = Field(default_factory=list)
    search_diagnostics: SearchDiagnostics = Field(default_factory=SearchDiagnostics)
    # What this call cost the deployment, in USD as decimal text. "0" for a scraped answer.
    cost_usd: str = "0"
    guidance: str = ""
    error: str | None = None


class SourceStatus(CamelModel):
    """What one literature source did for one search."""

    model_config = ConfigDict(frozen=True)

    source: str
    results: int = 0
    error: str | None = None


class PaperOut(CamelModel):
    """One paper, as the model reads it."""

    title: str
    year: int | None = None
    journal: str | None = None
    authors: list[str] = Field(default_factory=list)
    doi: str | None = None
    pmid: str | None = None
    url: str | None = None
    abstract: str = ""


class LiteratureSearchOut(CamelModel):
    """Ranked papers. The leading ones carry the abstract."""

    query: str
    results: list[PaperOut] = Field(default_factory=list)
    sources: list[SourceRef] = Field(default_factory=list)
    sources_status: list[SourceStatus] = Field(default_factory=list)
    guidance: str = ""

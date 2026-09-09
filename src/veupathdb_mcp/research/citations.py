"""What a served result cites, and the filters and options a call names."""

import re
from datetime import UTC, datetime
from string import ascii_lowercase
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, model_validator
from veupathdb.model import CamelModel

LiteratureSource = Literal[
    "europepmc",
    "crossref",
    "openalex",
    "semanticscholar",
    "pubmed",
    "arxiv",
    "biorxiv",
    "medrxiv",
    "all",
]
LiteratureSort = Literal["relevance", "newest"]


class LiteratureFilters(BaseModel):
    """Post-retrieval filters for literature results.

    A tool argument is snake_case on the wire, so this is not a CamelModel.
    """

    year_from: int | None = None
    year_to: int | None = None
    author_includes: str | None = None
    title_includes: str | None = None
    journal_includes: str | None = None
    doi_equals: str | None = None
    pmid_equals: str | None = None
    require_doi: bool = False


class LiteratureOutputOptions(BaseModel):
    """Output formatting options for literature results.

    A tool argument is snake_case on the wire, so this is not a CamelModel.
    """

    include_abstract: bool = True
    abstract_max_chars: int = 500
    max_authors: int = 5


def _slug_token(value: str | None, *, max_len: int = 32) -> str:
    t = (value or "").strip().lower()
    if not t:
        return ""
    t = re.sub(r"[^a-z0-9]+", "", t)
    return t[:max_len]


def _suggest_tag(citation: "Citation") -> str:
    """Derive a short slug tag from a Citation's metadata."""
    title = citation.title
    authors = citation.authors
    year = citation.year

    first_author = authors[0] if authors else None
    parts = first_author.split(",")[0].split() if first_author else []
    first_last = _slug_token(parts[0]) if parts else ""

    if first_last:
        return f"{first_last}{year}" if year else first_last

    first_word = _slug_token(title.split(maxsplit=1)[0]) if title.split() else ""
    tag_from_word = f"{first_word}{year}" if (first_word and year) else first_word
    if tag_from_word:
        return tag_from_word

    stable = _slug_token(title, max_len=20) or _slug_token(
        citation.doi or citation.pmid or citation.url, max_len=20
    )
    return stable or str(citation.source)


class Citation(CamelModel):
    id: str
    source: Literal[
        "web",
        "europepmc",
        "crossref",
        "openalex",
        "semanticscholar",
        "pubmed",
        "arxiv",
        "biorxiv",
        "medrxiv",
    ]
    title: str
    url: str | None = None
    authors: list[str] | None = None
    year: int | None = None
    doi: str | None = None
    pmid: str | None = None
    snippet: str | None = None
    accessed_at: str | None = None
    tag: str = ""

    @model_validator(mode="after")
    def _set_tag(self) -> "Citation":
        if not self.tag:
            self.tag = _suggest_tag(self)
        return self


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _new_citation_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


def ensure_unique_citation_tags(citations: list["Citation"]) -> None:
    """Ensure all citation tags are unique by appending suffixes if needed.

    :param citations: Citation objects.

    """
    used: dict[str, int] = {}
    for c in citations:
        base = _slug_token(c.tag, max_len=40) or "ref"
        n = used.get(base, 0)
        if n == 0:
            tag = base
        elif n <= len(ascii_lowercase):
            tag = f"{base}{ascii_lowercase[n - 1]}"
        else:
            tag = f"{base}_{n + 1}"
        used[base] = n + 1
        c.tag = tag

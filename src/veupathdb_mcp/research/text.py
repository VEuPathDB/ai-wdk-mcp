"""Text normalization, fuzzy ranking, filtering, and page summary extraction."""

import html
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from urllib.parse import parse_qs, unquote, urlparse

import httpx
from rapidfuzz import fuzz
from veupathdb import get_logger

from veupathdb_mcp.research.citations import LiteratureFilters
from veupathdb_mcp.research.literature.papers import ParsedPaper

logger = get_logger(__name__)

_ELLIPSIS = "..."


@dataclass
class LiteratureItemContext:
    """Fields extracted from a literature result for filter evaluation."""

    title: str
    authors: list[str] | None
    year: int | None
    doi: str | None
    pmid: str | None
    journal: str | None


# Paragraphs shorter than this are navigation or footer text, not content.
_MIN_PARAGRAPH_LENGTH = 60

BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)


def norm_text(value: str | None) -> str:
    """Normalize text for comparison."""
    return (value or "").strip().lower()


def limit_authors(authors: list[str] | None, max_authors: int) -> list[str] | None:
    """Limit the author list. A max of -1 means no limit."""
    cleaned = [author for author in authors or [] if author.strip()]
    if not cleaned:
        return None
    if max_authors == -1 or len(cleaned) <= max_authors:
        return cleaned
    n = int(max_authors)
    return ["et al."] if n <= 0 else [*cleaned[:n], "et al."]


def truncate_text(text: str | None, max_chars: int) -> str | None:
    """Cut text to max_chars, the ellipsis included, and mark it as cut."""
    t = (text or "").strip()
    if not t:
        return None
    if len(t) <= max_chars:
        return t
    return t[: max_chars - len(_ELLIPSIS)].rstrip() + _ELLIPSIS


def strip_tags(text: str) -> str:
    """Remove HTML tags and normalize whitespace."""
    cleaned = re.sub(r"<[^>]+>", " ", text)
    cleaned = html.unescape(cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def decode_ddg_redirect(href: str) -> str:
    """Decode a DuckDuckGo redirect URL to its target URL."""
    h = (href or "").strip()
    if not h:
        return h
    if h.startswith("//"):
        h = "https:" + h
    result = h
    try:
        u = urlparse(h)
        if "duckduckgo.com" in (u.netloc or "") and u.path.startswith("/l/"):
            targets = parse_qs(u.query or "").get("uddg") or []
            if targets and targets[0]:
                result = unquote(targets[0])
    except (ValueError, TypeError, KeyError) as exc:
        logger.debug("Failed to decode DDG redirect URL", error=str(exc))
    return result


def norm_for_match(text: str | None) -> str:
    """Normalize text for fuzzy matching."""
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def fallback_ratio(a: str, b: str) -> float:
    """Return a similarity ratio from 0 to 100 using SequenceMatcher."""
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio() * 100.0


def fuzzy_score(query: str, text: str) -> float:
    """Score the fuzzy similarity between a query and a text."""
    q = norm_for_match(query)
    t = norm_for_match(text)
    if not q or not t:
        return 0.0
    try:
        return float(fuzz.token_set_ratio(q, t))
    except (ValueError, TypeError) as exc:
        logger.debug("rapidfuzz unavailable, using fallback ratio", error=str(exc))
        return fallback_ratio(q, t)


_MIN_ABSTRACT_SCORE_LEN = 40


def rerank_score(query: str, paper: ParsedPaper) -> tuple[float, dict[str, float]]:
    """Score a literature result and return the score with its breakdown."""
    title = paper.title
    abstract = paper.abstract or paper.snippet or ""
    journal = paper.journal_title or ""
    title_s = fuzzy_score(query, title)
    # Only score the abstract when it is long enough to carry real content.
    abs_s = (
        fuzzy_score(query, abstract)
        if len(abstract.strip()) >= _MIN_ABSTRACT_SCORE_LEN
        else 0.0
    )
    journal_s = fuzzy_score(query, journal) if journal else 0.0
    score = 0.70 * title_s + 0.28 * abs_s + 0.02 * journal_s
    return score, {"title": title_s, "abstract": abs_s, "journal": journal_s}


def passes_filters(item: LiteratureItemContext, filters: LiteratureFilters) -> bool:
    """Report whether a literature result passes every filter."""
    year_ok = (
        filters.year_from is None
        or (item.year is not None and item.year >= filters.year_from)
    ) and (
        filters.year_to is None
        or (item.year is not None and item.year <= filters.year_to)
    )
    doi_ok = not filters.require_doi or bool((item.doi or "").strip())
    exact_ok = (
        filters.doi_equals is None
        or norm_text(item.doi) == norm_text(filters.doi_equals)
    ) and (
        filters.pmid_equals is None
        or norm_text(item.pmid) == norm_text(filters.pmid_equals)
    )
    needle_author = (
        norm_text(filters.author_includes)
        if filters.author_includes is not None
        else None
    )
    haystack = " ".join(norm_text(a) for a in (item.authors or []))
    text_ok = (
        (
            filters.title_includes is None
            or norm_text(filters.title_includes) in norm_text(item.title)
        )
        and (
            filters.journal_includes is None
            or norm_text(filters.journal_includes) in norm_text(item.journal)
        )
        and (needle_author is None or needle_author in haystack)
    )
    return year_ok and doi_ok and exact_ok and text_ok


def dedupe_key(paper: ParsedPaper) -> str:
    """Build a deduplication key for a literature result.

    Key priority is pmid, then doi, then url, then title and year.
    """
    for prefix, value in [("pmid", paper.pmid), ("doi", paper.doi), ("url", paper.url)]:
        if value and value.strip():
            return f"{prefix}:{value.strip().lower()}"
    return f"title:{norm_text(paper.title)}|year:{paper.year}"


_HEAD_LIMIT = 32 * 1024

_META_PATTERNS = [
    re.compile(
        r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)["\']',
        re.IGNORECASE,
    ),
    re.compile(
        r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']+)["\']',
        re.IGNORECASE,
    ),
    re.compile(
        r'<meta[^>]+name=["\']twitter:description["\'][^>]+content=["\']([^"\']+)["\']',
        re.IGNORECASE,
    ),
]


def _extract_meta_description(text: str) -> str | None:
    """Return the first meta description that matches a known pattern."""
    for pat in _META_PATTERNS:
        m = pat.search(text)
        if m:
            return strip_tags(m.group(1)) or None
    return None


def _extract_best_paragraph(text: str) -> str | None:
    """Return the longest non-boilerplate ``<p>`` content."""
    paras = re.findall(r"<p[^>]*>(.*?)</p>", text, flags=re.IGNORECASE | re.DOTALL)
    best: str | None = None
    for p in paras:
        txt = strip_tags(p)
        low = txt.lower()
        if len(txt) < _MIN_PARAGRAPH_LENGTH:
            continue
        if "toggle navigation" in low or "main navigation" in low:
            continue
        if best is None or len(txt) > len(best):
            best = txt
    return best


async def fetch_page_summary(
    client: httpx.AsyncClient, url: str | None, *, max_chars: int
) -> str | None:
    """Fetch a web page and extract a short text summary.

    Reading stops at the end of the head element or at the byte limit.
    Meta descriptions take priority over the longest paragraph. A page that
    cannot be read carries no summary, so one refusal never ends a search.
    """
    u = (url or "").strip()
    is_skippable = not u or u.lower().endswith(".pdf") or "scholar.google." in u
    if is_skippable:
        return None

    buf = ""
    head_closed = False
    fetch_error = False
    try:
        async with client.stream(
            "GET",
            u,
            follow_redirects=True,
            headers={"Referer": "https://duckduckgo.com/"},
        ) as resp:
            resp.raise_for_status()
            async for chunk in resp.aiter_text():
                buf += chunk
                if "</head>" in buf.lower():
                    head_closed = True
                    break
                if len(buf) >= _HEAD_LIMIT:
                    break
    except (httpx.HTTPError, httpx.InvalidURL, ValueError, TypeError, OSError) as exc:
        logger.debug("Failed to fetch page for summary extraction", error=str(exc))
        fetch_error = True

    if fetch_error:
        return None
    search_region = buf[: buf.lower().find("</head>") + 7] if head_closed else buf
    desc = _extract_meta_description(search_region)
    text = desc or _extract_best_paragraph(buf)
    return truncate_text(text, max_chars)

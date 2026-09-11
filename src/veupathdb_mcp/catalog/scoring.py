"""IDF scoring, keyword boosting, and record-type ranking for search discovery."""

import math
from collections import Counter
from dataclasses import dataclass, field

from veupathdb.wdk import WDKSearch

from veupathdb_mcp.catalog.models import SearchMatch

# ---------------------------------------------------------------------------
# Scoring constants
# ---------------------------------------------------------------------------

_WEIGHT_SEARCH_NAME = 5.0
_WEIGHT_DISPLAY_NAME = 3.0
_WEIGHT_DESCRIPTION = 1.0
_KEYWORD_BOOST = 20.0
_MIN_TERM_LEN = 3


@dataclass
class SearchCorpus:
    """Corpus statistics for IDF scoring in search ranking."""

    doc_count: int = 1
    term_counts: dict[str, int] = field(default_factory=dict)


_RECORD_CLASS_LABELS = {
    "transcript": "genes/transcripts",
    "gene": "genes",
    "snp": "SNPs",
    "popsetsequence": "popset sequences",
    "est": "ESTs",
    "compound": "compounds",
    "pathway": "pathways",
}

# Highest priority first.
_PREFERRED_RECORD_TYPES = ("transcript", "gene")


def score_search(
    *,
    query_terms: list[str],
    keywords: list[str],
    search_name: str,
    display_name: str,
    description: str,
    corpus: SearchCorpus | None = None,
) -> float:
    """Score a search against query terms and keywords.

    Each keyword found in the search name adds a flat boost. Each query term
    adds its field weight times its IDF. Terms shorter than the minimum length
    are ignored.
    """
    score = 0.0
    name_lower = search_name.lower()
    display_lower = display_name.lower()
    desc_lower = description.lower()

    for kw in keywords:
        if kw.lower() in name_lower:
            score += _KEYWORD_BOOST

    sc = corpus or SearchCorpus()
    term_counts = sc.term_counts
    n = max(sc.doc_count, 1)

    for term in query_terms:
        if len(term) < _MIN_TERM_LEN:
            continue
        term_lower = term.lower()
        df = term_counts.get(term_lower, 1)
        idf = math.log(n / (1 + df)) + 1.0

        if term_lower in name_lower:
            score += _WEIGHT_SEARCH_NAME * idf
        if term_lower in display_lower:
            score += _WEIGHT_DISPLAY_NAME * idf
        if term_lower in desc_lower:
            score += _WEIGHT_DESCRIPTION * idf

    return score


def is_chooser_search(search: WDKSearch) -> bool:
    """Return True for a routing search that carries no real parameters.

    WDK marks these with ``hideOperation`` in ``websiteProperties``.
    """
    ws_props = search.properties.get("websiteProperties", [])
    return "hideOperation" in ws_props


def record_type_priority(record_type: str) -> int:
    """Rank a record type. A lower number is a higher priority."""
    rt = record_type.lower()
    for i, preferred in enumerate(_PREFERRED_RECORD_TYPES):
        if preferred in rt:
            return i
    return 100


def resolve_returns(output_record_class_name: str) -> str:
    """Map a WDK output record class name to a human-readable label."""
    if not output_record_class_name:
        return ""
    rc_lower = output_record_class_name.lower()
    for key, label in _RECORD_CLASS_LABELS.items():
        if key in rc_lower:
            return label
    return ""


def score_candidates(
    candidates: list[tuple[WDKSearch, str]],
    terms: list[str],
    kw_list: list[str],
) -> list[tuple[float, SearchMatch]]:
    """Score each candidate search and return ``(score, entry)`` pairs."""
    corpus_counts: Counter[str] = Counter()
    for s, _ in candidates:
        haystack = f"{s.url_segment} {s.display_name} {s.description}".lower()
        for term in terms:
            if len(term) >= _MIN_TERM_LEN and term in haystack:
                corpus_counts[term] += 1

    doc_count = len(candidates)
    scored: list[tuple[float, SearchMatch]] = []
    for s, rt_name in candidates:
        display = s.display_name or s.url_segment
        desc = s.description

        sc = score_search(
            query_terms=terms,
            keywords=kw_list,
            search_name=s.url_segment,
            display_name=display,
            description=desc,
            corpus=SearchCorpus(doc_count=doc_count, term_counts=dict(corpus_counts)),
        )
        category = ""
        dc = s.properties.get("displayCategory", [])
        if dc:
            category = str(dc[0])

        entry = SearchMatch(
            name=s.url_segment,
            display_name=display,
            description=s.summary or desc,
            record_type=rt_name,
            category=category,
            returns=resolve_returns(s.output_record_class_name),
        )
        scored.append((sc, entry))
    return scored

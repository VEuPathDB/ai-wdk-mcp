"""Query intent detection, relevance scoring, and deduplication for search
results fetched wide from site-search and WDK."""

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from rapidfuzz import fuzz

_MIN_ORGANISM_MATCH_SCORE = 0.60


def score_text_match(query: str, value: str) -> float:
    """Score how well the query matches the value, from 0.0 to 1.0.

    Exact and prefix matches outrank fuzzy matches, because gene ID lookups
    depend on them.
    """
    q = query.strip().lower()
    v = value.strip().lower()

    if not q or not v:
        return 0.0
    if q == v:
        return 1.0
    if v.startswith(q):
        return 0.95
    if q in v:
        return 0.80

    # WRatio returns the best of several ratio strategies on a 0-100 scale.
    return fuzz.WRatio(q, v) / 100.0


PRIMARY_MATCH_FIELDS: frozenset[str] = frozenset(
    {
        "gene_source_id",
        "gene_name",
        "gene_product",
        "gene_type",
        "gene_organism_full",
        "primary_key",
        "hyperlinkName",
    }
)

SECONDARY_MATCH_FIELDS: frozenset[str] = frozenset(
    {
        "gene_Notes",
        "gene_PubMed",
        "gene_UserCommentContent",
        "autocomplete",
        "MULTIgene_Notes",
        "MULTIgene_PubMed",
    }
)


def score_field_quality(matched_fields: Sequence[str]) -> float:
    """Score a match by which fields it hit."""
    if not matched_fields:
        return 0.0
    if any(f in PRIMARY_MATCH_FIELDS for f in matched_fields):
        return 1.0
    if any(f in SECONDARY_MATCH_FIELDS for f in matched_fields):
        return -0.5
    return 0.0


@dataclass
class ScoredResult[T]:
    """A search result with an attached relevance score."""

    result: T
    score: float
    source: str = ""


def dedup_and_sort[T](
    results: Sequence[ScoredResult[T]],
    key_fn: Callable[[T], str],
) -> list[ScoredResult[T]]:
    """Deduplicate results by key, keeping the highest-scoring entry."""
    best: dict[str, ScoredResult[T]] = {}
    for sr in results:
        k = key_fn(sr.result)
        if not k:
            continue
        existing = best.get(k)
        if existing is None or sr.score > existing.score:
            best[k] = sr
    return sorted(
        best.values(),
        key=lambda x: (-x.score, key_fn(x.result)),
    )


_GENE_ID_PREFIX_RE = re.compile(
    r"^[A-Za-z]{2,8}[_\-]?\d",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class QueryIntent:
    """Detected intent behind a raw search query."""

    raw: str
    is_gene_id_like: bool = False
    implied_organism: str | None = None
    implied_organism_score: float = 0.0
    wildcard_ids: tuple[str, ...] = ()


def _build_wildcard_ids(query: str) -> tuple[str, ...]:
    """Generate wildcard ID patterns for a gene-ID-like query."""
    q = query.strip()
    if not q:
        return ()

    patterns: list[str] = []
    if "_" in q:
        patterns.append(f"{q}*")
    else:
        upper = q.upper()
        patterns.append(f"{upper}_*")
        patterns.append(f"{upper}*")
        if upper != q:
            patterns.append(f"{q}*")

    return tuple(dict.fromkeys(patterns))


def analyse_query(
    query: str,
    available_organisms: list[str],
    organism_scorer: Callable[[str, str], float] | None = None,
) -> QueryIntent:
    """Analyse a query string to detect search intent."""
    q = query.strip()
    if not q:
        return QueryIntent(raw=q)

    scorer = organism_scorer or _default_organism_scorer
    is_id_like = bool(_GENE_ID_PREFIX_RE.match(q))

    best_org: str | None = None
    best_score: float = 0.0

    for org in available_organisms:
        s = scorer(q, org)
        if s > best_score:
            best_score = s
            best_org = org

    if best_score < _MIN_ORGANISM_MATCH_SCORE:
        best_org = None
        best_score = 0.0

    wildcard_ids = _build_wildcard_ids(q) if is_id_like else ()

    return QueryIntent(
        raw=q,
        is_gene_id_like=is_id_like,
        implied_organism=best_org,
        implied_organism_score=best_score,
        wildcard_ids=wildcard_ids,
    )


def _default_organism_scorer(query: str, organism: str) -> float:
    """Score an organism name by substring containment."""
    q = query.strip().lower()
    o = organism.strip().lower()
    if q == o:
        return 1.0
    if q in o:
        return 0.7
    return 0.0

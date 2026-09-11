"""Search public WDK strategies by text relevance.

Fetches the public strategy list from WDK and ranks by token overlap
against the user's query. Returns the top N matches.
"""

import re

from veupathdb import JSONObject
from veupathdb.wdk import WDKStrategySummary

from veupathdb_mcp.embeddings.record_manager import (
    IndexEntry,
    search_index,
    sync_index,
)
from veupathdb_mcp.locks import KeyedLock

# Field weights: name matters most, description second, nameOfFirstStep third.
_FIELD_WEIGHTS: list[tuple[str, float]] = [
    ("name", 3.0),
    ("description", 2.0),
    ("name_of_first_step", 1.0),
    ("author", 0.5),
    ("record_class_name", 0.5),
]

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_MIN_TOKEN_LEN = 2


def _tokenize(text: str) -> set[str]:
    """Lowercase tokenization — split on non-alphanumeric, keep tokens >= 2 chars."""
    return {
        tok for tok in _TOKEN_RE.findall(text.lower()) if len(tok) >= _MIN_TOKEN_LEN
    }


def _score_strategy(strategy: WDKStrategySummary, query_tokens: set[str]) -> float:
    """Score a strategy against query tokens using weighted field overlap."""
    if not query_tokens:
        return 0.0
    total = 0.0
    for field, weight in _FIELD_WEIGHTS:
        value = getattr(strategy, field, "")
        if not value:
            continue
        field_tokens = _tokenize(value)
        if not field_tokens:
            continue
        overlap = len(query_tokens & field_tokens)
        total += weight * (overlap / len(query_tokens))
    return total


def rank_public_strategies(
    strategies: list[WDKStrategySummary],
    query: str,
    limit: int = 3,
) -> list[JSONObject]:
    """Rank public strategies by text relevance to query.

    :param strategies: Typed public strategy summaries from WDK.
    :param query: User's search query.
    :param limit: Maximum results to return.
    :returns: Top matches as serialized dicts, excluding zero-score entries.
    """
    query_tokens = _tokenize(query)
    if not query_tokens:
        return []

    scored = [
        (strategy, _score_strategy(strategy, query_tokens)) for strategy in strategies
    ]
    scored = [(s, score) for s, score in scored if score > 0]
    scored.sort(key=lambda x: x[1], reverse=True)
    return [
        s.model_dump(by_alias=True, exclude_none=True, mode="json")
        for s, _ in scored[:limit]
    ]


_DEFAULT_SEMANTIC_MIN_SCORE = 0.4

# One index per site. The list is fetched inside the call that ranks it, so the
# process that fetched it is the process that syncs it.
_SYNC_PASS = KeyedLock()


def public_strategy_index_id(site_id: str) -> str:
    """The record manager's id for one site's public strategies."""
    return f"public-strategies:{site_id}"


def _strategy_doc(strategy: WDKStrategySummary) -> str:
    return f"{strategy.name}. {strategy.description}. {strategy.name_of_first_step}".strip()


async def rank_public_strategies_semantic(
    strategies: list[WDKStrategySummary],
    query: str,
    *,
    site_id: str,
    limit: int = 3,
    min_score: float = _DEFAULT_SEMANTIC_MIN_SCORE,
) -> list[JSONObject]:
    """Rank public strategies by embedding cosine similarity to the query.

    Bridges paraphrase gaps that lexical token overlap misses ("immunization
    targets" vs "vaccine antigens"). The site's index is brought level with the
    fetched list first, so an unchanged list embeds nothing.
    """
    if not strategies or not query.strip():
        return []
    index_id = public_strategy_index_id(site_id)
    by_id = {str(strategy.strategy_id): strategy for strategy in strategies}
    async with _SYNC_PASS(site_id):
        await sync_index(
            index_id,
            [
                IndexEntry(entry_id=entry_id, text=_strategy_doc(strategy))
                for entry_id, strategy in by_id.items()
            ],
        )
    hits = await search_index(index_id, query, len(by_id))
    ranked = [
        by_id[hit.entry_id]
        for hit in hits
        if hit.similarity >= min_score and hit.entry_id in by_id
    ]
    return [
        s.model_dump(by_alias=True, exclude_none=True, mode="json")
        for s in ranked[:limit]
    ]

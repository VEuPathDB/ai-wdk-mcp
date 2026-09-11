"""Semantic similarity matching for search discovery.

Boosts search candidates by cosine similarity from the site's embedding index,
and injects high-similarity searches that keyword scoring missed.
"""

from veupathdb import get_logger
from veupathdb.errors import VEuPathDBError
from veupathdb.wdk import WDKSearch

from veupathdb_mcp.catalog.discovery import SearchCatalog
from veupathdb_mcp.catalog.discovery_service import DiscoveryService
from veupathdb_mcp.catalog.models import SearchMatch
from veupathdb_mcp.catalog.scoring import resolve_returns
from veupathdb_mcp.embeddings.errors import SemanticIndexUnavailableError

logger = get_logger(__name__)

# A cosine of 0.7 is worth a strong lexical match. Measured on the plasmodb
# snapshot: the top lexical score of five research queries has a median of
# 49.2, and 0.7 * 70.0 is 49.0.
_SEMANTIC_BOOST = 70.0

# Cosine below this does not name a search the keywords missed.
_MIN_SEMANTIC_SIM = 0.35

_SEMANTIC_TOP_K = 50


def build_search_match(search: WDKSearch, rt: str) -> SearchMatch:
    """Build a SearchMatch from a WDKSearch for semantic injection."""
    display = search.display_name or search.url_segment
    category = ""
    dc = search.properties.get("displayCategory", [])
    if dc:
        category = str(dc[0])
    returns = resolve_returns(search.output_record_class_name)
    return SearchMatch(
        name=search.url_segment,
        display_name=display,
        description=search.summary or search.description,
        record_type=rt,
        category=category,
        returns=returns,
    )


async def apply_semantic_bonus(
    scored: list[tuple[float, SearchMatch]],
    discovery: DiscoveryService,
    site_id: str,
    query: str,
    record_types: list[str],
) -> None:
    """Boost scored entries by cosine similarity from the site's index.

    An index that cannot answer leaves the lexical ranking as it is.
    """
    if not query:
        return
    try:
        catalog = await discovery.get_catalog(site_id)
        index = catalog.get_semantic_index()
        if index is None:
            return
        sem_results = await index.query(query, _SEMANTIC_TOP_K)
    except SemanticIndexUnavailableError as exc:
        logger.warning(
            "Search ranking is lexical only", site_id=site_id, error=str(exc)
        )
        return
    except VEuPathDBError, OSError, ValueError, TypeError:
        logger.debug("Semantic bonus failed (non-fatal)", exc_info=True)
        return

    rt_set = set(record_types)
    in_scope = [(name, rt, sim) for name, rt, sim in sem_results if _fits(rt, rt_set)]
    sem_scores = {name: sim for name, _, sim in in_scope}

    for i, (sc, entry) in enumerate(scored):
        sim = sem_scores.get(entry.name, 0.0)
        if sim > 0.0:
            scored[i] = (sc + _SEMANTIC_BOOST * sim, entry)

    _inject_missed(scored, catalog, in_scope)


def _fits(record_type: str, rt_set: set[str]) -> bool:
    """Whether a hit's record type is one the caller asked for."""
    return not rt_set or record_type in rt_set


def _inject_missed(
    scored: list[tuple[float, SearchMatch]],
    catalog: SearchCatalog,
    hits: list[tuple[str, str, float]],
) -> None:
    """Add the high-similarity searches keyword scoring never proposed."""
    existing_names = {entry.name for _, entry in scored}
    for search_name, rt, sim in hits:
        if search_name in existing_names or sim < _MIN_SEMANTIC_SIM:
            continue
        search = catalog.find_search(rt, search_name)
        if search is None:
            continue
        scored.append((_SEMANTIC_BOOST * sim, build_search_match(search, rt)))

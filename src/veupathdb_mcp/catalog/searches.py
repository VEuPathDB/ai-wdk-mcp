"""Search listing, filtering, and discovery. Scoring, semantic matching, and
candidate collection live in sibling modules."""

import re
from collections.abc import Awaitable, Callable
from typing import Literal

from veupathdb.domain.search import SearchContext
from veupathdb.domain.strategy.graph_model import StrategyStep
from veupathdb.logging import get_logger
from veupathdb.model import CamelModel
from veupathdb.wdk.factory import get_wdk_client
from veupathdb.wdk.wdk_models import WDKRecordType, WDKSearch

from veupathdb_mcp.catalog.discovery_service import (
    get_discovery_service,
)
from veupathdb_mcp.catalog.models import SearchMatch
from veupathdb_mcp.catalog.scoring import (
    is_chooser_search,
    record_type_priority,
    score_candidates,
)
from veupathdb_mcp.catalog.search_collection import (
    apply_site_search_bonus,
    collect_search_candidates,
    resolve_record_types,
)
from veupathdb_mcp.catalog.semantic_matching import apply_semantic_bonus

logger = get_logger(__name__)

# A search name is unique across all record types on a site.
ResolveRecordType = Callable[[str], Awaitable[str | None]]

_MIN_QUERY_TOKENS = 2


class SearchQueryRejection(CamelModel):
    """Why a query cannot rank the catalog, in the shape the caller returns."""

    error: Literal["query_required", "query_too_vague"]
    message: str
    query: str | None = None
    examples: list[str] | None = None


class VagueSearchQueryError(Exception):
    """A catalog query that carries too little signal to rank searches."""

    def __init__(self, rejection: SearchQueryRejection) -> None:
        self.rejection = rejection
        super().__init__(rejection.message)


def _query_tokens(text: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9][A-Za-z0-9._-]{2,}", (text or "").lower())


def _query_rejection(query: str, *, has_keywords: bool) -> SearchQueryRejection | None:
    """Refuse a query with too few terms to separate one search from another.

    Keywords carry the specificity on their own, so they allow a short query.
    """
    q = (query or "").strip()
    if not q and not has_keywords:
        return SearchQueryRejection(
            error="query_required",
            message="search_for_searches(query=...) requires a non-empty query.",
        )
    if len(_query_tokens(q)) < _MIN_QUERY_TOKENS and not has_keywords:
        return SearchQueryRejection(
            error="query_too_vague",
            message=(
                "search_for_searches(query=...) requires 2+ specific keywords. "
                "Be descriptive."
            ),
            query=q,
            examples=[
                "vector salivary gland",
                "gametocyte RNA-seq",
                "drug resistance markers",
                "liver stage expression",
            ],
        )
    return None


async def get_raw_record_types(site_id: str) -> list[WDKRecordType]:
    """Return the full WDK record type objects for a site."""
    discovery = get_discovery_service()
    return await discovery.get_record_types(site_id)


async def get_raw_searches(site_id: str, record_type: str) -> list[WDKSearch]:
    """Return the raw WDK search objects for a record type."""
    discovery = get_discovery_service()
    return await discovery.get_searches(site_id, record_type)


async def browse_search_categories(
    site_id: str,
    record_type: str = "transcript",
) -> list[dict[str, str | int | list[str]]]:
    """Return the ontology search categories with example search names.

    Searches with no category form one universal group.
    """
    discovery = get_discovery_service()
    catalog = await discovery.get_catalog(site_id)
    searches = await discovery.get_searches(site_id, record_type)

    groups: dict[str, list[str]] = {}
    for s in searches:
        if s.full_name.startswith("InternalQuestions."):
            continue
        if is_chooser_search(s):
            continue
        cat = catalog.get_search_category(s.url_segment) or "(universal)"
        groups.setdefault(cat, []).append(s.display_name or s.url_segment)

    result: list[dict[str, str | int | list[str]]] = []
    for cat in sorted(groups, key=lambda c: (c == "(universal)", -len(groups[c]))):
        # Universal searches are few, so they are all listed.
        max_examples = len(groups[cat]) if cat == "(universal)" else 5
        result.append(
            {
                "category": cat,
                "count": len(groups[cat]),
                "examples": groups[cat][:max_examples],
            }
        )
    return result


async def list_searches(site_id: str, record_type: str) -> list[dict[str, str]]:
    """List searches for a record type.

    Only names are returned, because descriptions make the payload large.
    """
    discovery = get_discovery_service()
    searches = await discovery.get_searches(site_id, record_type)
    result: list[dict[str, str]] = []
    for s in searches:
        if s.full_name.startswith("InternalQuestions."):
            continue
        result.append(
            {
                "name": s.url_segment,
                "displayName": s.display_name,
            }
        )
    return result


async def list_transforms(site_id: str, record_type: str) -> list[dict[str, str]]:
    """List the searches that accept an input step, with their descriptions.

    These searches chain one step onto another.
    """
    discovery = get_discovery_service()
    searches = await discovery.get_searches(site_id, record_type)
    result: list[dict[str, str]] = []
    for s in searches:
        if not s.allowed_primary_input_record_class_names:
            continue
        if s.full_name.startswith("InternalQuestions."):
            continue
        result.append(
            {
                "name": s.url_segment,
                "displayName": s.display_name,
                "description": s.description,
            }
        )
    return result


async def search_for_searches(
    site_id: str,
    record_type: str | list[str] | None,
    query: str,
    *,
    keywords: list[str] | None = None,
    category: str | None = None,
    limit: int = 20,
) -> list[SearchMatch]:
    """Find searches that match a query or keywords.

    A category restricts the candidates to that category plus the
    universal searches. A query too vague to rank raises ``VagueSearchQueryError``.
    """
    kw_list = keywords or []
    rejection = _query_rejection(query, has_keywords=bool(kw_list))
    if rejection is not None:
        raise VagueSearchQueryError(rejection)
    discovery = get_discovery_service()

    record_types = await resolve_record_types(discovery, site_id, record_type)

    raw_terms = re.findall(r"[A-Za-z0-9_]+", query or "")
    terms = [t.lower() for t in raw_terms if t]

    candidates = await collect_search_candidates(
        discovery, site_id, record_types, category=category
    )
    scored = score_candidates(candidates, terms, kw_list)

    await apply_site_search_bonus(scored, site_id, query, limit)

    await apply_semantic_bonus(scored, discovery, site_id, query, record_types)

    scored.sort(
        key=lambda item: (
            -item[0],
            record_type_priority(item[1].record_type),
            item[1].display_name,
        )
    )

    # Relevance is the score normalized against the best score.
    max_score = scored[0][0] if scored else 1.0
    if max_score <= 0:
        max_score = 1.0

    seen: set[str] = set()
    result: list[SearchMatch] = []
    for sc, entry in scored:
        if entry.name in seen:
            continue
        seen.add(entry.name)
        result.append(
            SearchMatch(
                name=entry.name,
                display_name=entry.display_name,
                description=entry.description,
                record_type=entry.record_type,
                category=entry.category,
                returns=entry.returns,
                relevance=sc / max_score,
            )
        )
        if len(result) >= limit:
            break

    return result


async def read_search_definition(
    site_id: str, record_type: str, search_name: str
) -> WDKSearch:
    """The expanded WDK definition of one search: its metadata and parameters."""
    details = await get_wdk_client(site_id).get_search_details(
        record_type, search_name, expand_params=True
    )
    return details.search_data


async def resolve_search_record_type(
    site_id: str, search_name: str, record_type: str | None
) -> str:
    """Return the record type of a search, reading the catalog when none is given."""
    if record_type:
        return record_type
    ctx = SearchContext(
        site_id=site_id, search_name=search_name, record_type="transcript"
    )
    return await find_record_type_for_search(ctx)


async def find_record_type_for_search(ctx: SearchContext) -> str:
    """Resolve which record type owns a search name.

    The context record type applies when the search is not in the catalog.
    """
    discovery = get_discovery_service()
    catalog = await discovery.get_catalog(ctx.site_id)
    resolved = catalog.find_record_type_for_search(ctx.search_name)
    return resolved or ctx.record_type


async def make_record_type_resolver(site_id: str) -> ResolveRecordType:
    """Create a record type resolver over the cached search catalog.

    The resolver makes no HTTP calls.
    """
    discovery = get_discovery_service()
    catalog = await discovery.get_catalog(site_id)

    async def resolve(search_name: str) -> str | None:
        return catalog.find_record_type_for_search(search_name)

    return resolve


async def assign_step_record_classes(
    steps: dict[str, StrategyStep],
    resolver: ResolveRecordType,
) -> None:
    """Give each step that states a search the record class WDK lists it under.

    A combine states no search, so its class is left for ``record_class_of`` to
    read off the steps it consumes.
    """
    for step in steps.values():
        if not step.search_name:
            continue
        resolved = await resolver(step.search_name)
        if resolved:
            step.record_class = resolved

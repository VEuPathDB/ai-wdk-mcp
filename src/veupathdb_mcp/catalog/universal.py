"""The searches a discovery result offers whatever it ranked."""

from veupathdb_mcp.catalog.discovery_service import get_discovery_service
from veupathdb_mcp.catalog.models import SearchMatch
from veupathdb_mcp.catalog.radio_pairs import radio_pairs
from veupathdb_mcp.catalog.scoring import search_match
from veupathdb_mcp.catalog.search_collection import resolve_record_types
from veupathdb_mcp.catalog.search_offer import is_ranked_search

# The text search a site offers for any question about its genes.
TEXT_SEARCH = "GenesByText"


async def universal_searches(
    site_id: str, record_type: str | list[str] | None
) -> tuple[SearchMatch, ...]:
    """The searches a discovery result offers whatever it ranked.

    They are the site's text search and every search that declares a radio
    pair, read from the held catalog.
    """
    discovery = get_discovery_service()
    record_types = await resolve_record_types(discovery, site_id, record_type)
    offered: dict[str, SearchMatch] = {}
    for rt_name in record_types:
        for s in await discovery.get_searches(site_id, rt_name):
            universal = s.url_segment == TEXT_SEARCH or bool(radio_pairs(s.properties))
            if universal and is_ranked_search(s) and s.url_segment not in offered:
                offered[s.url_segment] = search_match(s, rt_name)
    text = offered.pop(TEXT_SEARCH, None)
    return (*([text] if text else []), *offered.values())

"""The organisms a site declares, read from the site's own WDK."""

from veupathdb.domain.parameters.wdk_vocab import vocab_keys
from veupathdb.domain.search import SearchContext

from veupathdb_mcp.catalog.discovery_service import get_discovery_service

TAXON_SEARCH = "SequencesByTaxon"
"""The search whose organism parameter carries the site's taxon tree.

VEuPathDB's own site-search client reads the same one
(``web-monorepo`` ``packages/libs/web-common/src/hooks/organisms.ts``).
"""

ORGANISM_PARAM = "organism"


async def list_organisms(site_id: str) -> list[str]:
    """Every organism the site declares, sorted. Empty on a non-genomic site."""
    discovery = get_discovery_service()
    catalog = await discovery.get_catalog(site_id)
    record_type = catalog.find_record_type_for_search(TAXON_SEARCH)
    if record_type is None:
        return []

    response = await discovery.get_search_details(
        SearchContext(
            site_id=site_id, record_type=record_type, search_name=TAXON_SEARCH
        ),
    )
    for param in response.search_data.parameters or []:
        if param.name == ORGANISM_PARAM:
            return sorted(vocab_keys(param.vocabulary))
    return []

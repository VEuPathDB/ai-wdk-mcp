"""The organisms a site declares, and the parameter of a search that names them."""

from collections.abc import Sequence

from veupathdb.domain import SearchContext
from veupathdb.domain.parameters import VocabOption, exact_entry, vocab_keys
from veupathdb.wdk import WDKParameter

from veupathdb_mcp.catalog.discovery_service import get_discovery_service

TAXON_SEARCH = "SequencesByTaxon"
"""The search whose organism parameter carries the site's taxon tree.

VEuPathDB's own site-search client reads the same one
(``web-monorepo`` ``packages/libs/web-common/src/hooks/organisms.ts``).
"""


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
    parameters = response.search_data.parameters or []
    marked = _marked_organism(parameters)
    by_name = {p.name: p for p in parameters}
    return [] if marked is None else sorted(vocab_keys(by_name[marked].vocabulary))


def _lists_organisms(parameter: WDKParameter, site: Sequence[VocabOption]) -> bool:
    leaves = vocab_keys(parameter.vocabulary)
    return bool(leaves) and all(exact_entry(site, leaf) is not None for leaf in leaves)


def _marked_organism(parameters: Sequence[WDKParameter]) -> str | None:
    """The parameter that marks reference organisms among its entries."""
    return next((p.name for p in parameters if p.is_organism), None)


async def organism_parameter_of(
    site_id: str, parameters: Sequence[WDKParameter]
) -> str | None:
    """The marked parameter, or else the one with an organism list whose every leaf
    is one of the site's organisms."""
    marked = _marked_organism(parameters)
    listed = [p for p in parameters if "organismProperties" in p.properties]
    if marked is not None or not listed:
        return marked
    site = [VocabOption(value=o, display=o) for o in await list_organisms(site_id)]
    return next((p.name for p in listed if _lists_organisms(p, site)), None)


async def organism_parameter(
    site_id: str, record_type: str, search_name: str
) -> str | None:
    """The organism parameter of the search, or None."""
    details = await get_discovery_service().get_search_details(
        SearchContext(site_id=site_id, record_type=record_type, search_name=search_name)
    )
    return await organism_parameter_of(site_id, details.search_data.parameters or [])

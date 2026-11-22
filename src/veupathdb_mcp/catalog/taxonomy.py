"""OrthoMCL's taxonomy, read once per site from its helper record, and the
species tree either phyletic search names its codes from."""

from veupathdb.domain.parameters import PHYLETIC_EXPRESSION_PARAM, PhyleticTree
from veupathdb.wdk import (
    ORTHO_TAXONOMY_RECORD_TYPE,
    ORTHO_TAXONOMY_REPORT,
    ORTHO_TAXONOMY_SEARCH,
    WDKSearch,
    WDKSearchConfig,
    get_wdk_client,
    ortho_taxonomy_of,
    phyletic_tree_of,
)

from veupathdb_mcp.catalog.site_record_types import declared_record_types

PHYLETIC_PROFILE_SEARCH = "GenesByOrthologPattern"

_HELD: dict[str, PhyleticTree] = {}


async def serves_ortho_taxonomy(site_id: str) -> bool:
    """Whether the site's declared record types list OrthoMCL's helper record."""
    return ORTHO_TAXONOMY_RECORD_TYPE in await declared_record_types(site_id)


async def ortho_taxonomy(site_id: str) -> PhyleticTree | None:
    """The site's clade and species tree, or ``None`` when the site holds none."""
    held = _HELD.get(site_id)
    if held is not None:
        return held
    if not await serves_ortho_taxonomy(site_id):
        return None
    answer = await get_wdk_client(site_id).run_search_report(
        ORTHO_TAXONOMY_RECORD_TYPE,
        ORTHO_TAXONOMY_SEARCH,
        WDKSearchConfig(),
        ORTHO_TAXONOMY_REPORT,
    )
    tree = ortho_taxonomy_of(answer)
    if tree is not None:
        _HELD[site_id] = tree
    return tree


async def phyletic_tree_for_search(
    site_id: str, definition: WDKSearch
) -> PhyleticTree | None:
    """The tree a search's species codes come from: its own maps, or the site's
    taxonomy for OrthoMCL's expression search. ``None`` for any other search."""
    params = definition.parameters or []
    if any(param.name == PHYLETIC_EXPRESSION_PARAM for param in params):
        return await ortho_taxonomy(site_id)
    return phyletic_tree_of(params)

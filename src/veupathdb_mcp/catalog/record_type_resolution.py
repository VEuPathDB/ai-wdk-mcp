"""Record-type resolution for searches that may live under multiple types.

VEuPathDB searches registered under both ``transcript`` and ``gene``
produce correct results only under ``transcript`` for strategy building,
so resolution prefers it. Failing that, falls back to a global catalog
lookup before giving up.
"""

from __future__ import annotations

from veupathdb.errors import VEuPathDBError
from veupathdb.logging import get_logger

from veupathdb_mcp.catalog.discovery import SearchCatalog
from veupathdb_mcp.catalog.discovery_service import (
    get_discovery_service,
)
from veupathdb_mcp.wdk.record_types import resolve_record_type


async def get_catalog(site_id: str) -> SearchCatalog:
    discovery = get_discovery_service()
    return await discovery.get_catalog(site_id)


logger = get_logger(__name__)


async def resolve_record_type_value(
    site_id: str,
    record_type: str | None,
) -> str | None:
    if not record_type:
        return record_type
    catalog = await get_catalog(site_id)
    return resolve_record_type(catalog.get_record_types(), record_type) or record_type


async def find_record_type_for_search(
    site_id: str,
    record_type: str | None,
    search_name: str | None,
    *,
    require_match: bool = False,
    allow_fallback: bool = True,
) -> str | None:
    resolved = await resolve_record_type_value(site_id, record_type)
    if not search_name:
        return resolved
    return await _lookup_record_type_for_search(
        site_id,
        search_name,
        resolved,
        require_match=require_match,
        allow_fallback=allow_fallback,
    )


async def _lookup_record_type_for_search(
    site_id: str,
    search_name: str,
    resolved: str | None,
    *,
    require_match: bool,
    allow_fallback: bool,
) -> str | None:
    catalog = await get_catalog(site_id)
    if resolved == "gene" and catalog.find_search("transcript", search_name):
        return "transcript"
    if resolved and catalog.find_search(resolved, search_name):
        return resolved
    if not allow_fallback:
        return None if require_match else resolved
    found = catalog.find_record_type_for_search(search_name)
    return found or (None if require_match else resolved)


def _scan_record_type_excluding(
    catalog: SearchCatalog,
    search_name: str,
    exclude: str,
) -> str | None:
    for rt_name in catalog._searches:
        if rt_name != exclude and catalog.find_search(rt_name, search_name):
            return rt_name
    return None


async def find_record_type_hint(
    site_id: str,
    search_name: str,
    exclude: str | None = None,
) -> str | None:
    try:
        catalog = await get_catalog(site_id)
    except VEuPathDBError as exc:
        logger.warning(
            "Failed to fetch search catalog for record type hint",
            search_name=search_name,
            error=str(exc),
        )
        return None
    found = catalog.find_record_type_for_search(search_name)
    if found and exclude and found == exclude:
        return _scan_record_type_excluding(catalog, search_name, exclude)
    return found

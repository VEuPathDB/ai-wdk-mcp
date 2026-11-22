"""The record types a site declares: its loaded catalog's, or one read of the
site's /record-types held for the process."""

from __future__ import annotations

from veupathdb.wdk import get_wdk_client

from veupathdb_mcp.catalog.discovery_service import get_discovery_service

_LISTED: dict[str, frozenset[str]] = {}


async def declared_record_types(site_id: str) -> frozenset[str]:
    held = get_discovery_service().held_record_types(site_id)
    if held is not None:
        return frozenset(record.url_segment for record in held)
    if site_id not in _LISTED:
        served = await get_wdk_client(site_id).get_record_types()
        _LISTED[site_id] = frozenset(record.url_segment for record in served)
    return _LISTED[site_id]

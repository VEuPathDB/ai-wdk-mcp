"""Sites and record types catalog functions."""

from veupathdb.wdk import SiteInfo, get_site_router

from veupathdb_mcp.catalog.discovery_service import (
    get_discovery_service,
)
from veupathdb_mcp.catalog.models import RecordTypeInfo


async def list_sites() -> list[SiteInfo]:
    """List all available VEuPathDB sites."""
    return get_site_router().list_sites()


async def get_record_types(site_id: str) -> list[RecordTypeInfo]:
    """Get record types for a specific site."""
    discovery = get_discovery_service()
    record_types = await discovery.get_record_types(site_id)
    return [
        RecordTypeInfo(
            name=rt.url_segment,
            display_name=rt.display_name,
            description=rt.description,
        )
        for rt in record_types
    ]

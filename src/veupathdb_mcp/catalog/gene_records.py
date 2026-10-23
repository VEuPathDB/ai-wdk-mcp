from __future__ import annotations

from veupathdb.errors import ValidationError
from veupathdb.wdk import get_wdk_client

from veupathdb_mcp.catalog.discovery_service import get_discovery_service

GENE_RECORD_TYPE = "gene"

_LISTED: dict[str, frozenset[str]] = {}


class NoGeneRecordsError(ValidationError):
    def __init__(self, site_id: str) -> None:
        self.site_id = site_id
        super().__init__(
            title="The site serves no gene records",
            detail=(
                f"{site_id} lists no {GENE_RECORD_TYPE} record type, "
                "so it reads no gene by id"
            ),
        )


async def _listed(site_id: str) -> frozenset[str]:
    held = get_discovery_service().held_record_types(site_id)
    if held is not None:
        return frozenset(record.url_segment for record in held)
    if site_id not in _LISTED:
        served = await get_wdk_client(site_id).get_record_types()
        _LISTED[site_id] = frozenset(record.url_segment for record in served)
    return _LISTED[site_id]


async def require_gene_records(site_id: str) -> None:
    if GENE_RECORD_TYPE not in await _listed(site_id):
        raise NoGeneRecordsError(site_id)

from __future__ import annotations

from veupathdb.errors import ValidationError

from veupathdb_mcp.catalog.site_record_types import declared_record_types

GENE_RECORD_TYPE = "gene"


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


async def require_gene_records(site_id: str) -> None:
    if GENE_RECORD_TYPE not in await declared_record_types(site_id):
        raise NoGeneRecordsError(site_id)

"""The gene record type a site serves, read once per site in a process."""

from __future__ import annotations

import pydantic
from pydantic import BaseModel, ConfigDict, Field
from veupathdb.errors import DataParsingError
from veupathdb.wdk import get_wdk_client

from veupathdb_mcp.wdk.site_cache import SiteCache

GENE_RECORD_TYPE_PATH = "/record-types/gene"


class DeclaredTable(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow")

    name: str


class GeneRecordType(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    primary_key_column_refs: list[str] = Field(default=[], alias="primaryKeyColumnRefs")
    tables: list[DeclaredTable] | None = None

    @property
    def names(self) -> list[str] | None:
        return None if self.tables is None else [table.name for table in self.tables]


async def _read(site_id: str) -> GeneRecordType:
    served = await get_wdk_client(site_id).get(GENE_RECORD_TYPE_PATH)
    try:
        return GeneRecordType.model_validate(served)
    except pydantic.ValidationError as exc:
        msg = f"the gene record type of {site_id} is not readable"
        raise DataParsingError(msg) from exc


_SERVED: SiteCache[GeneRecordType] = SiteCache()


async def gene_record_type(site_id: str) -> GeneRecordType:
    return await _SERVED.read(site_id, _read)

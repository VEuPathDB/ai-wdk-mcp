"""The columns, tables and searches of a record type that is not a gene."""

from __future__ import annotations

from difflib import get_close_matches
from enum import StrEnum

from pydantic import ConfigDict
from veupathdb.model import CamelModel
from veupathdb.wdk import WDKRecordType, WDKSearch

from veupathdb_mcp.catalog.discovery import SearchCatalog
from veupathdb_mcp.catalog.discovery_service import get_discovery_service
from veupathdb_mcp.record_fields import (
    GENE_RECORD_TYPES,
    ColumnInfo,
    TableInfo,
    shown_columns,
    shown_tables,
)


class UnreadableRecordError(ValueError):
    """A record type, search, column or table the site does not serve here."""


class NameKind(StrEnum):
    """What a name the site does not serve was meant to name."""

    RECORD_TYPE = "record type"
    SEARCH = "search"
    COLUMN = "column"
    TABLE = "table"


class UnknownNameError(UnreadableRecordError):
    """A name the site does not serve, with the nearest names it does."""

    def __init__(self, kind: NameKind, name: str, known: list[str], where: str) -> None:
        near = get_close_matches(name, known, n=5, cutoff=0.4) or known[:10]
        super().__init__(f"{where} has no {kind} '{name}'. It has: {', '.join(near)}.")


class SearchInfo(CamelModel):
    """One search that returns the record type."""

    model_config = ConfigDict(frozen=True)

    name: str
    display_name: str


class RecordColumns(CamelModel):
    """What one record type of a site carries, and the searches that return it."""

    site_id: str
    record_type: str
    display_name: str
    columns: list[ColumnInfo]
    tables: list[TableInfo]
    searches: list[SearchInfo]


def listed_searches(
    catalog: SearchCatalog, searches: list[WDKSearch]
) -> list[SearchInfo]:
    """The searches a researcher can run, by name and display name."""
    return [
        SearchInfo(name=search.url_segment, display_name=search.display_name)
        for search in searches
        if catalog.lists(search)
    ]


async def readable_record_types(site_id: str) -> list[WDKRecordType]:
    """The site's record types that are not genes."""
    held = await get_discovery_service().get_record_types(site_id)
    return [rt for rt in held if rt.url_segment not in GENE_RECORD_TYPES]


async def readable_record_type(site_id: str, record_type: str) -> WDKRecordType:
    """The record type, when the site serves it and it is not a gene record type."""
    if record_type in GENE_RECORD_TYPES:
        message = (
            f"'{record_type}' records are genes. A gene result is read as a "
            "strategy step, not as a table."
        )
        raise UnreadableRecordError(message)
    held = await readable_record_types(site_id)
    found = next((rt for rt in held if rt.url_segment == record_type), None)
    if found is None:
        names = [rt.url_segment for rt in held]
        raise UnknownNameError(NameKind.RECORD_TYPE, record_type, names, site_id)
    return found


async def searches_of(site_id: str, record_type: str) -> list[WDKSearch]:
    """Every search the site's catalog holds for the record type."""
    return await get_discovery_service().get_searches(site_id, record_type)


async def record_columns(site_id: str, record_type: str) -> RecordColumns:
    """The columns, tables and searches of one record type of a site."""
    found = await readable_record_type(site_id, record_type)
    searches = await searches_of(site_id, record_type)
    catalog = await get_discovery_service().get_catalog(site_id)
    return RecordColumns(
        site_id=site_id,
        record_type=record_type,
        display_name=found.display_name or record_type,
        columns=shown_columns(found),
        tables=shown_tables(found),
        searches=listed_searches(catalog, searches),
    )

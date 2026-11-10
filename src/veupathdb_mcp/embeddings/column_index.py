"""The semantic index of the columns and tables of a site's records that are not genes."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from veupathdb.wdk import WDKRecordType

from veupathdb_mcp.embeddings.record_manager import IndexEntry, SyncReport, sync_index
from veupathdb_mcp.record_fields import (
    GENE_RECORD_TYPES,
    shown_columns,
    shown_tables,
)

type ColumnKind = Literal["column", "table"]


def column_index_id(site_id: str) -> str:
    """The index that holds one site's record columns."""
    return f"record-columns:{site_id}"


def _entry_id(record_type: str, kind: ColumnKind, name: str) -> str:
    return f"{record_type}/{kind}/{name}"


def column_entries(record_types: Sequence[WDKRecordType]) -> list[IndexEntry]:
    """One entry per column and per table of each record type that is not a gene."""
    entries: list[IndexEntry] = []
    for record_type in record_types:
        if record_type.url_segment in GENE_RECORD_TYPES:
            continue
        owner = record_type.display_name or record_type.url_segment
        entries.extend(
            IndexEntry(
                entry_id=_entry_id(record_type.url_segment, "column", column.name),
                text=f"{owner}: {column.display_name}. {column.help}".strip(),
            )
            for column in shown_columns(record_type)
        )
        entries.extend(
            IndexEntry(
                entry_id=_entry_id(record_type.url_segment, "table", table.name),
                text=(
                    f"{owner}: {table.display_name}. Columns: "
                    + ", ".join(column.display_name for column in table.columns)
                ),
            )
            for table in shown_tables(record_type)
        )
    return entries


async def sync_record_columns(
    site_id: str, record_types: Sequence[WDKRecordType]
) -> SyncReport:
    """Make the site's column index hold exactly its records' columns and tables."""
    return await sync_index(column_index_id(site_id), column_entries(record_types))

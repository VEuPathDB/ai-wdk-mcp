"""A semantic index of the columns and tables of a site's records that are not genes."""

from __future__ import annotations

from veupathdb.model import CamelModel

from veupathdb_mcp.embeddings.column_index import ColumnKind, column_index_id
from veupathdb_mcp.embeddings.record_manager import search_index
from veupathdb_mcp.record_fields import shown_columns, shown_tables
from veupathdb_mcp.records.columns import readable_record_types

COLUMN_FLOOR = 0.35


class ColumnMatch(CamelModel):
    """A column or table of one record type that is close to the query."""

    site_id: str
    record_type: str
    record_display_name: str
    kind: ColumnKind
    name: str
    display_name: str
    similarity: float


async def rank_record_columns(
    site_id: str, query: str, top_k: int = 5
) -> list[ColumnMatch]:
    """The site's record columns and tables closest to the query, best first."""
    hits = await search_index(column_index_id(site_id), query, top_k)
    held = {rt.url_segment: rt for rt in await readable_record_types(site_id)}
    matches: list[ColumnMatch] = []
    for hit in hits:
        record_type, kind, name = hit.entry_id.split("/", 2)
        owner = held.get(record_type)
        if hit.similarity < COLUMN_FLOOR or owner is None:
            continue
        shown = (
            {column.name: column.display_name for column in shown_columns(owner)}
            if kind == "column"
            else {table.name: table.display_name for table in shown_tables(owner)}
        )
        if name not in shown:
            continue
        matches.append(
            ColumnMatch(
                site_id=site_id,
                record_type=record_type,
                record_display_name=owner.display_name or record_type,
                kind="column" if kind == "column" else "table",
                name=name,
                display_name=shown[name],
                similarity=round(hit.similarity, 3),
            )
        )
    return matches

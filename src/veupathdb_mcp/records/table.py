"""One search's records, or one of their tables, read as rows of chosen columns."""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import Field, JsonValue, TypeAdapter
from veupathdb import JSONObject
from veupathdb.errors import VEuPathDBError
from veupathdb.model import CamelModel
from veupathdb.text import strip_html_tags
from veupathdb.wdk import (
    WDKAnswer,
    WDKLinkAttribute,
    WDKRecordType,
    WDKSearch,
    WDKSearchConfig,
    get_wdk_client,
)

from veupathdb_mcp.record_fields import ColumnInfo, shown_columns, shown_tables
from veupathdb_mcp.records.columns import (
    NameKind,
    UnknownNameError,
    UnreadableRecordError,
    readable_record_type,
    searches_of,
)

DEFAULT_ROWS = 50
MAX_ROWS = 200
READ_RECORDS = 5000

_TABLE_ROWS: TypeAdapter[list[dict[str, JsonValue]]] = TypeAdapter(
    list[dict[str, JsonValue]]
)


class TableRow(CamelModel):
    """One row: the record it belongs to and the text of each chosen column."""

    record: str
    values: dict[str, str]


class SearchTable(CamelModel):
    """The rows a search returned, with how many there were and how many show."""

    site_id: str
    record_type: str
    search_name: str
    search_display_name: str
    table: str | None
    columns: list[ColumnInfo]
    total_records: int
    matched_rows: int
    rows: list[TableRow]
    note: str


def cell_text(value: JsonValue) -> str:
    """The text a reader sees in one cell."""
    match value:
        case None:
            return ""
        case {**fields}:
            return WDKLinkAttribute.model_validate(fields).display_text
        case _:
            return strip_html_tags(str(value)).strip()


async def _search(site_id: str, record_type: str, search_name: str) -> WDKSearch:
    searches = await searches_of(site_id, record_type)
    found = next((s for s in searches if s.url_segment == search_name), None)
    if found is None:
        names = [s.url_segment for s in searches]
        raise UnknownNameError(
            NameKind.SEARCH,
            search_name,
            names,
            f"The {record_type} records of {site_id}",
        )
    return found


def _chosen(
    asked: Sequence[str], offered: list[ColumnInfo], default: list[str], where: str
) -> list[ColumnInfo]:
    by_name = {column.name: column for column in offered}
    for name in asked:
        if name not in by_name:
            raise UnknownNameError(NameKind.COLUMN, name, list(by_name), where)
    names = list(asked) or [name for name in default if name in by_name]
    return [by_name[name] for name in names or list(by_name)[:10]]


def _columns(
    record_type: WDKRecordType,
    search: WDKSearch,
    asked: Sequence[str],
    table: str | None,
) -> list[ColumnInfo]:
    if table is None:
        offered = [
            *shown_columns(record_type),
            *(
                ColumnInfo(name=a.name, display_name=a.display_name)
                for a in search.dynamic_attributes
            ),
        ]
        return _chosen(asked, offered, search.default_attributes, search.url_segment)
    tables = {found.name: found for found in shown_tables(record_type)}
    if table not in tables:
        raise UnknownNameError(
            NameKind.TABLE, table, list(tables), record_type.url_segment
        )
    return _chosen(asked, tables[table].columns, [], table)


def _row(name: str, cells: dict[str, JsonValue], columns: list[ColumnInfo]) -> TableRow:
    return TableRow(
        record=name,
        values={column.name: cell_text(cells.get(column.name)) for column in columns},
    )


def _rows(
    answer: WDKAnswer, columns: list[ColumnInfo], table: str | None
) -> list[TableRow]:
    rows: list[TableRow] = []
    for record in answer.records:
        name = strip_html_tags(record.display_name).strip()
        if table is None:
            rows.append(_row(name, record.attributes, columns))
            continue
        listed = _TABLE_ROWS.validate_python(record.tables.get(table, []))
        rows.extend(_row(name, cells, columns) for cells in listed)
    return rows


def _holds(row: TableRow, text: str) -> bool:
    wanted = text.casefold()
    return any(wanted in cell.casefold() for cell in [row.record, *row.values.values()])


def _counted(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def _note(total: int, read: int, matched: int, shown: int) -> str:
    parts = []
    if total > read:
        parts.append(
            f"The search returned {total} records; the first {read} were read."
        )
    else:
        parts.append(f"The search returned {_counted(total, 'record')}.")
    if matched > shown:
        parts.append(
            f"Showing {shown} of {matched} rows. Name a narrower contains, or "
            "read again with a higher limit."
        )
    else:
        parts.append(f"Showing all {_counted(matched, 'row')}.")
    return " ".join(parts)


class TableRequest(CamelModel):
    """One search to read, and which of its rows and columns.

    With no table, a row is one record and its columns are the record's. With a
    table, a row is one row of that table. No columns named means the search's
    default columns. contains keeps the rows that hold its text.
    """

    record_type: str
    search_name: str
    parameters: dict[str, str] = Field(default_factory=dict)
    columns: list[str] = Field(default_factory=list)
    table: str | None = None
    contains: str | None = None
    limit: int = Field(default=DEFAULT_ROWS, ge=1, le=MAX_ROWS)


async def _answer(
    site_id: str, request: TableRequest, chosen: list[ColumnInfo]
) -> WDKAnswer:
    table = request.table
    report: JSONObject = {
        "attributes": [] if table else [column.name for column in chosen],
        "tables": [table] if table else [],
        "pagination": {"offset": 0, "numRecords": READ_RECORDS},
    }
    try:
        return await get_wdk_client(site_id).run_search_report(
            request.record_type,
            request.search_name,
            WDKSearchConfig(parameters=request.parameters),
            report,
        )
    except VEuPathDBError as exc:
        message = f"{site_id} refused {request.search_name}: {exc}"
        raise UnreadableRecordError(message) from exc


async def read_search_table(site_id: str, request: TableRequest) -> SearchTable:
    """Run a search of a record type that is not a gene and read its rows."""
    found = await readable_record_type(site_id, request.record_type)
    search = await _search(site_id, request.record_type, request.search_name)
    chosen = _columns(found, search, request.columns, request.table)
    answer = await _answer(site_id, request, chosen)
    rows = _rows(answer, chosen, request.table)
    if request.contains:
        rows = [row for row in rows if _holds(row, request.contains)]
    shown = rows[: request.limit]
    total = answer.meta.total_count or len(answer.records)
    return SearchTable(
        site_id=site_id,
        record_type=request.record_type,
        search_name=request.search_name,
        search_display_name=search.display_name,
        table=request.table,
        columns=chosen,
        total_records=total,
        matched_rows=len(rows),
        rows=shown,
        note=_note(total, len(answer.records), len(rows), len(shown)),
    )

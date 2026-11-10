"""The columns and tables an expanded record type carries, as a reader names them."""

from __future__ import annotations

from pydantic import ConfigDict, Field
from veupathdb.model import CamelModel
from veupathdb.wdk import WDKAttributeField, WDKRecordType

GENE_RECORD_TYPES = frozenset({"gene", "transcript"})


class ColumnInfo(CamelModel):
    """One column a record carries."""

    model_config = ConfigDict(frozen=True)

    name: str
    display_name: str
    help: str = ""


class TableInfo(CamelModel):
    """One table a record carries, and its columns."""

    model_config = ConfigDict(frozen=True)

    name: str
    display_name: str
    columns: list[ColumnInfo] = Field(default_factory=list)


def _column(field: WDKAttributeField) -> ColumnInfo:
    return ColumnInfo(
        name=field.name,
        display_name=field.display_name or field.name,
        help=field.help or "",
    )


def shown_columns(record_type: WDKRecordType) -> list[ColumnInfo]:
    """The columns a reader can ask for, in the site's order."""
    fields = record_type.attributes or list((record_type.attributes_map or {}).values())
    return [_column(field) for field in fields if field.is_displayable]


def shown_tables(record_type: WDKRecordType) -> list[TableInfo]:
    """The tables a reader can ask for, each with its columns."""
    return [
        TableInfo(
            name=table.name,
            display_name=table.display_name or table.name,
            columns=[_column(field) for field in table.attributes],
        )
        for table in record_type.tables or []
        if table.is_displayable
    ]


__all__ = [
    "GENE_RECORD_TYPES",
    "ColumnInfo",
    "TableInfo",
    "shown_columns",
    "shown_tables",
]

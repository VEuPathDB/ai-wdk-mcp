"""Served reads of records that are not genes: their columns, and a search's rows."""

from __future__ import annotations

from fastmcp.exceptions import ToolError

from veupathdb_mcp import records
from veupathdb_mcp.records import (
    RecordColumns,
    SearchTable,
    TableRequest,
    UnreadableRecordError,
)


async def list_record_columns(site_id: str, record_type: str) -> RecordColumns:
    """List the columns, tables and searches of one record type that is not a gene.

    Genome facts such as gene counts, BUSCO scores and assembly versions are
    columns of the organism record on a genomics site. OrthoMCL keeps its
    proteome counts in the DataSummary table of its helper record.

    Args:
        site_id: VEuPathDB site, for example 'veupathdb'.
        record_type: A record type the site serves, for example 'organism'.
    """
    try:
        return await records.record_columns(site_id, record_type)
    except UnreadableRecordError as exc:
        raise ToolError(str(exc)) from exc


async def read_search_table(site_id: str, request: TableRequest) -> SearchTable:
    """Run one search of a record type that is not a gene and read its rows.

    With no table, a row is one record. With a table, a row is one row of that
    table. contains keeps the rows that hold its text, for example an organism
    name. The answer names how many rows matched and how many show.

    Args:
        site_id: VEuPathDB site, for example 'veupathdb'.
        request: The search, its parameter values, the columns or the table,
            the text rows must hold, and how many rows to show.
    """
    try:
        return await records.read_search_table(site_id, request)
    except UnreadableRecordError as exc:
        raise ToolError(str(exc)) from exc

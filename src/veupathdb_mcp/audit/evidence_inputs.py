"""Reads the evidence tables a site's gene record type declares, a gene's served rows
of them, and the organism report that states each genome's provenance."""

from __future__ import annotations

import pydantic
from veupathdb.errors import DataParsingError, VEuPathDBErrorCode

from veupathdb_mcp.audit.evidence import (
    GeneEvidence,
    GenomeProvenance,
    provenance_of,
    requested_tables,
)
from veupathdb_mcp.audit.gene_ids import id_pairs
from veupathdb_mcp.audit.gene_models import ORGANISM_ATTRIBUTE, gene_record
from veupathdb_mcp.audit.genes import organism_report
from veupathdb_mcp.audit.served import located
from veupathdb_mcp.tool_errors import ToolErrorPayload, tool_error
from veupathdb_mcp.wdk.gene_record_type import gene_record_type

GENOME_ATTRIBUTES = (
    "source_id",
    "organism_full",
    "genome_source",
    "genome_version",
    "annotation_source",
    "annotation_version",
    "database_version",
    "build_introduced",
    "build_latest_update",
    "is_reference_strain",
    "ncbi_tax_id",
)


async def declared_tables(site_id: str) -> list[str]:
    names = (await gene_record_type(site_id)).names
    if names is None:
        msg = f"the gene record type of {site_id} declares no readable tables"
        raise DataParsingError(msg)
    return names


async def gene_evidence(site_id: str, gene: str) -> GeneEvidence | ToolErrorPayload:
    match await located(site_id, [gene]):
        case ToolErrorPayload() as refusal:
            return refusal
        case rows:
            [named] = id_pairs([gene], rows)
    declared = await declared_tables(site_id)
    record = await gene_record(
        site_id, named.resolved, [ORGANISM_ATTRIBUTE], requested_tables(declared)
    )
    try:
        return GeneEvidence.from_record(named, record, declared)
    except pydantic.ValidationError as exc:
        parts = sorted({str(error["loc"][0]) for error in exc.errors()})
        msg = (
            f"the gene record of {named.resolved} on {site_id} serves unreadable "
            f"evidence: {', '.join(parts)}"
        )
        raise DataParsingError(msg) from exc


async def genome_provenance(
    site_id: str, organism: str
) -> GenomeProvenance | ToolErrorPayload:
    answer = await organism_report(site_id, GENOME_ATTRIBUTES)
    try:
        provenance = provenance_of(answer, organism)
    except pydantic.ValidationError as exc:
        msg = f"the organism record of {organism} on {site_id} is not readable"
        raise DataParsingError(msg) from exc
    if provenance is None:
        return tool_error(
            VEuPathDBErrorCode.VALIDATION_ERROR,
            f"{organism} names no genome of {site_id}",
        )
    return provenance

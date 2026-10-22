"""What the organelle check reads from a site: a whole contig, and a reference gene's
protein and the genetic code its own coding sequence reads."""

from __future__ import annotations

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator
from veupathdb.errors import VEuPathDBErrorCode
from veupathdb.jbrowse import GenomeReader, get_jbrowse_client

from veupathdb_mcp.audit.codes import GeneticCode, infer_code
from veupathdb_mcp.audit.gene_ids import GeneId, check_resolved, id_pairs
from veupathdb_mcp.audit.gene_models import gene_model, gene_organism
from veupathdb_mcp.audit.genes import GeneRow, genes_of_genome, is_coding
from veupathdb_mcp.audit.organelle import OrganelleCheck
from veupathdb_mcp.audit.served import (
    AUDIT_MAX_WINDOW_BASES,
    coding_dna,
    located,
    read_proteins,
    window_refusal,
)
from veupathdb_mcp.tool_errors import ToolErrorPayload, tool_error


class OrganelleInputs(BaseModel):
    model_config = ConfigDict(frozen=True)

    gene_ids: list[GeneId] = Field(min_length=1, max_length=1)
    contig: str
    reference_protein: str
    code: GeneticCode
    code_inferred: bool


class OrganelleGeneAudit(OrganelleCheck):
    gene_ids: list[GeneId]
    organism: str
    sequence_id: str
    reference_gene: str
    contig_length: int
    code: GeneticCode
    code_inferred: bool

    @model_validator(mode="after")
    def _named_as_resolved(self) -> Self:
        check_resolved(self.gene_ids, [self.reference_gene])
        return self


def first_coding_gene(rows: list[GeneRow]) -> GeneRow | None:
    return min(
        (row for row in rows if is_coding(row)),
        key=lambda row: row.start,
        default=None,
    )


async def _abbreviation(
    site_id: str, organism: str, sequence_id: str
) -> str | ToolErrorPayload:
    rows = await genes_of_genome(site_id, organism)
    first = first_coding_gene([row for row in rows if row.sequence_id == sequence_id])
    if first is None:
        return tool_error(
            VEuPathDBErrorCode.VALIDATION_ERROR,
            f"{sequence_id} holds no protein-coding gene of {organism} on {site_id}",
        )
    return await gene_organism(site_id, first.gene)


async def _reference_code(
    site_id: str, genome: GenomeReader, reference: GeneRow, protein: str
) -> GeneticCode | None:
    model = await gene_model(site_id, reference.gene)
    window = await genome.window(
        model.organism_abbrev, reference.sequence_id, reference.start, reference.end
    )
    return infer_code(coding_dna(window, model, reference.strand), protein)


async def _contig_inputs(
    site_id: str,
    abbrev: str,
    sequence_id: str,
    reference: GeneRow,
    protein: str,
    ids: list[GeneId],
) -> OrganelleInputs | ToolErrorPayload:
    genome = GenomeReader(get_jbrowse_client(site_id))
    length = await genome.sequence_length(abbrev, sequence_id)
    if length > AUDIT_MAX_WINDOW_BASES:
        return window_refusal(sequence_id, length)
    code = await _reference_code(site_id, genome, reference, protein)
    contig = await genome.window(abbrev, sequence_id, 1, length)
    return OrganelleInputs(
        gene_ids=ids,
        contig=contig.sequence,
        reference_protein=protein,
        code=code or GeneticCode.STANDARD,
        code_inferred=code is not None,
    )


async def organelle_inputs(
    site_id: str, organism: str, sequence_id: str, reference_gene: str
) -> OrganelleInputs | ToolErrorPayload:
    match await located(site_id, [reference_gene]):
        case ToolErrorPayload() as refusal:
            return refusal
        case rows:
            reference = rows[reference_gene]
    span = reference.end - reference.start + 1
    if span > AUDIT_MAX_WINDOW_BASES:
        return window_refusal(reference.gene, span)
    match await read_proteins(site_id, [reference.gene]):
        case ToolErrorPayload() as refusal:
            return refusal
        case proteins:
            protein = proteins[reference.gene]
    match await _abbreviation(site_id, organism, sequence_id):
        case ToolErrorPayload() as refusal:
            return refusal
        case str() as abbrev:
            return await _contig_inputs(
                site_id,
                abbrev,
                sequence_id,
                reference,
                protein,
                id_pairs([reference_gene], rows),
            )

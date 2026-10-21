"""What the served audit checks read from a site, and what each one answers."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict
from veupathdb.errors import VEuPathDBErrorCode
from veupathdb.jbrowse import GenomeReader, get_jbrowse_client

from veupathdb_mcp.audit.codes import reverse_complement
from veupathdb_mcp.audit.gene_models import gene_model
from veupathdb_mcp.audit.genes import GeneRow, gene_rows, proteins_of
from veupathdb_mcp.audit.pseudogene import PseudogeneCheck, ReferenceGene
from veupathdb_mcp.audit.selenocysteine import SecCheck, sec_tail
from veupathdb_mcp.tool_errors import ToolErrorPayload, tool_error

AUDIT_MAX_WINDOW_BASES = 250_000
PSEUDOGENE_PAD = 3000
PSEUDOGENE_MAX_CELLS = 200_000_000
SELENOPROTEIN_PAD = 300


class PseudogeneInputs(BaseModel):
    model_config = ConfigDict(frozen=True)

    reference: ReferenceGene
    strain_coding_dna: str


class SelenoproteinInputs(BaseModel):
    model_config = ConfigDict(frozen=True)

    model_protein: str
    reference_protein: str
    dna: str
    strand: Literal["+", "-"]


class PseudogeneCallAudit(PseudogeneCheck):
    strain_gene: str
    reference_gene: str


class SelenoproteinEndAudit(SecCheck):
    gene: str
    reference_gene: str


async def _located(
    site_id: str, gene_ids: list[str]
) -> dict[str, GeneRow] | ToolErrorPayload:
    rows = {row.gene: row for row in await gene_rows(site_id, gene_ids)}
    missing = [gene for gene in gene_ids if gene not in rows]
    if missing:
        return tool_error(
            VEuPathDBErrorCode.VALIDATION_ERROR,
            f"{', '.join(missing)} names no gene of {site_id}",
        )
    return rows


def _window_refusal(gene: str, length: int) -> ToolErrorPayload:
    return tool_error(
        VEuPathDBErrorCode.VALIDATION_ERROR,
        f"the {gene} window spans {length} bases; an audit reads at most "
        f"{AUDIT_MAX_WINDOW_BASES} bases of genome per window",
    )


async def pseudogene_inputs(
    site_id: str, strain_gene: str, reference_gene: str
) -> PseudogeneInputs | ToolErrorPayload:
    match await _located(site_id, [strain_gene, reference_gene]):
        case ToolErrorPayload() as refusal:
            return refusal
        case rows:
            strain, reference = rows[strain_gene], rows[reference_gene]
    reference_length = reference.end - reference.start + 1
    strain_length = strain.end - strain.start + 1 + 2 * PSEUDOGENE_PAD
    for gene, length in (
        (reference_gene, reference_length),
        (strain_gene, strain_length),
    ):
        if length > AUDIT_MAX_WINDOW_BASES:
            return _window_refusal(gene, length)
    if reference_length * strain_length > PSEUDOGENE_MAX_CELLS:
        return tool_error(
            VEuPathDBErrorCode.VALIDATION_ERROR,
            f"{reference_gene} spans {reference_length} bases and the {strain_gene} "
            f"window {strain_length} bases; the check aligns pairs whose product "
            f"is at most {PSEUDOGENE_MAX_CELLS}",
        )
    reference_model = await gene_model(site_id, reference_gene)
    if not reference_model.cds:
        return tool_error(
            VEuPathDBErrorCode.VALIDATION_ERROR,
            f"{reference_gene} has no CDS in its gene model on {site_id}",
        )
    strain_model = await gene_model(site_id, strain_gene)
    genome = GenomeReader(get_jbrowse_client(site_id))
    reference_window = await genome.window(
        reference_model.organism, reference.sequence_id, reference.start, reference.end
    )
    strain_window = await genome.window(
        strain_model.organism,
        strain.sequence_id,
        strain.start - PSEUDOGENE_PAD,
        strain.end + PSEUDOGENE_PAD,
    )
    strain_dna = strain_window.sequence
    return PseudogeneInputs(
        reference=ReferenceGene(
            dna=reference_window.sequence,
            cds=reference_model.cds,
            start=reference_window.start,
            end=reference_window.end,
            strand=reference.strand,
        ),
        strain_coding_dna=(
            strain_dna if strain.strand == "+" else reverse_complement(strain_dna)
        ),
    )


async def selenoprotein_inputs(
    site_id: str, gene: str, reference_gene: str
) -> SelenoproteinInputs | ToolErrorPayload:
    match await _located(site_id, [gene, reference_gene]):
        case ToolErrorPayload() as refusal:
            return refusal
        case rows:
            row = rows[gene]
    proteins = await proteins_of(site_id, [gene, reference_gene])
    missing = [name for name in (gene, reference_gene) if name not in proteins]
    if missing:
        return tool_error(
            VEuPathDBErrorCode.VALIDATION_ERROR,
            f"{', '.join(missing)} has no protein on {site_id}",
        )
    tail = sec_tail(proteins[reference_gene])
    if not tail:
        return tool_error(
            VEuPathDBErrorCode.VALIDATION_ERROR,
            f"{reference_gene} has no selenocysteine on {site_id}",
        )
    pad = SELENOPROTEIN_PAD + 3 * len(tail)
    length = row.end - row.start + 1 + 2 * pad
    if length > AUDIT_MAX_WINDOW_BASES:
        return _window_refusal(gene, length)
    model = await gene_model(site_id, gene)
    window = await GenomeReader(get_jbrowse_client(site_id)).window(
        model.organism, row.sequence_id, row.start - pad, row.end + pad
    )
    return SelenoproteinInputs(
        model_protein=proteins[gene],
        reference_protein=proteins[reference_gene],
        dna=window.sequence,
        strand=row.strand,
    )

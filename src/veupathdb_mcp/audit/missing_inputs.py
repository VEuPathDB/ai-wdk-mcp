"""What the missing-gene check reads from a site: the example gene, its protein and its
genetic code, the genes of both genomes, and the DNA between the two anchors."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field
from veupathdb.errors import VEuPathDBErrorCode
from veupathdb.jbrowse import GenomeReader, get_jbrowse_client

from veupathdb_mcp.audit.codes import GeneticCode, infer_code
from veupathdb_mcp.audit.gene_ids import GeneId, id_pairs
from veupathdb_mcp.audit.gene_models import gene_model, gene_organism
from veupathdb_mcp.audit.genes import GeneRow, genes_of_genome
from veupathdb_mcp.audit.missing import (
    MISSING_PAD,
    Anchors,
    find_anchors,
    group_members,
)
from veupathdb_mcp.audit.served import (
    AUDIT_MAX_WINDOW_BASES,
    coding_dna,
    located,
    read_proteins,
    window_refusal,
)
from veupathdb_mcp.audit.windows import WINDOW
from veupathdb_mcp.tool_errors import ToolErrorPayload, tool_error

MIN_PROTEIN = 2 * WINDOW


class AnchoredDna(BaseModel):
    model_config = ConfigDict(frozen=True)

    anchors: Anchors
    sequence: str
    start: int
    genes: list[GeneRow]
    code: GeneticCode
    code_inferred: bool


class MissingInputs(BaseModel):
    model_config = ConfigDict(frozen=True)

    gene_ids: list[GeneId] = Field(min_length=1, max_length=1)
    protein: str
    annotated_members: list[GeneRow] | None
    dna: AnchoredDna | None


async def _example(
    site_id: str, example: GeneRow, absent_organism: str
) -> str | ToolErrorPayload:
    gene = example.gene
    if example.organism == absent_organism:
        return tool_error(
            VEuPathDBErrorCode.VALIDATION_ERROR,
            f"{gene} is a gene of {absent_organism}; "
            "the absent organism is another one",
        )
    length = example.end - example.start + 1
    if length > AUDIT_MAX_WINDOW_BASES:
        return window_refusal(gene, length)
    match await read_proteins(site_id, [gene]):
        case ToolErrorPayload() as refusal:
            return refusal
        case proteins:
            protein = proteins[gene]
    if len(protein) < MIN_PROTEIN:
        return tool_error(
            VEuPathDBErrorCode.VALIDATION_ERROR,
            f"the protein of {gene} on {site_id} has {len(protein)} "
            f"residues; the check reads proteins of at least {MIN_PROTEIN}",
        )
    return protein


async def _example_code(
    site_id: str, example: GeneRow, protein: str
) -> tuple[GeneticCode, bool]:
    model = await gene_model(site_id, example.gene)
    window = await GenomeReader(get_jbrowse_client(site_id)).window(
        model.organism_abbrev, example.sequence_id, example.start, example.end
    )
    code = infer_code(coding_dna(window, model, example.strand), protein)
    return code or GeneticCode.STANDARD, code is not None


async def _between_anchors(
    site_id: str,
    example: GeneRow,
    protein: str,
    absent_organism: str,
    ids: list[GeneId],
) -> MissingInputs:
    absent_genes = await genes_of_genome(site_id, absent_organism)
    members = group_members(example, absent_genes)
    if members:
        return MissingInputs(
            gene_ids=ids, protein=protein, annotated_members=members, dna=None
        )
    neighbours = await genes_of_genome(site_id, example.organism)
    anchors = find_anchors(neighbours, example, absent_genes)
    if anchors is None:
        return MissingInputs(
            gene_ids=ids, protein=protein, annotated_members=members, dna=None
        )
    code, inferred = await _example_code(site_id, example, protein)
    low, high = anchors.between
    seqid = anchors.left.sequence_id
    abbrev = await gene_organism(site_id, anchors.left.gene)
    window = await GenomeReader(get_jbrowse_client(site_id)).window(
        abbrev, seqid, low - MISSING_PAD, high + MISSING_PAD
    )
    genes = [
        row
        for row in absent_genes
        if row.sequence_id == seqid
        and row.end >= window.start
        and row.start <= window.end
    ]
    return MissingInputs(
        gene_ids=ids,
        protein=protein,
        annotated_members=members,
        dna=AnchoredDna(
            anchors=anchors,
            sequence=window.sequence,
            start=window.start,
            genes=sorted(genes, key=lambda row: row.start),
            code=code,
            code_inferred=inferred,
        ),
    )


async def missing_inputs(
    site_id: str, example_gene: str, absent_organism: str
) -> MissingInputs | ToolErrorPayload:
    match await located(site_id, [example_gene]):
        case ToolErrorPayload() as refusal:
            return refusal
        case rows:
            example = rows[example_gene]
    match await _example(site_id, example, absent_organism):
        case ToolErrorPayload() as refusal:
            return refusal
        case str() as protein:
            return await _between_anchors(
                site_id,
                example,
                protein,
                absent_organism,
                id_pairs([example_gene], rows),
            )

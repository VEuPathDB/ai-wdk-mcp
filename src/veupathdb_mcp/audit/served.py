"""What the served audit checks read from a site, and what each one answers."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, model_validator
from veupathdb.errors import VEuPathDBErrorCode
from veupathdb.jbrowse import GenomeReader, GenomeWindow, get_jbrowse_client
from veupathdb.model import CamelModel

from veupathdb_mcp.audit.codes import GeneticCode, infer_code, reverse_complement
from veupathdb_mcp.audit.gene_models import GeneModel, gene_model
from veupathdb_mcp.audit.genes import GeneRow, gene_rows, orthologs_of, proteins_of
from veupathdb_mcp.audit.length import DnaWindow, LengthCheck
from veupathdb_mcp.audit.lengths import (
    Confirmable,
    LengthClass,
    NotChecked,
    call_length,
)
from veupathdb_mcp.audit.pseudogene import PseudogeneCheck, ReferenceGene
from veupathdb_mcp.audit.selenocysteine import SecCheck, sec_tail
from veupathdb_mcp.tool_errors import ToolErrorPayload, tool_error

AUDIT_MAX_WINDOW_BASES = 250_000
PSEUDOGENE_PAD = 3000
PSEUDOGENE_MAX_CELLS = 200_000_000
SELENOPROTEIN_PAD = 300
LENGTH_EDGE = 2000
LENGTH_MIN_FLANK = 6000
LENGTH_MAX_FLANK = 30000
LENGTH_FLANK_PER_RESIDUE = 12
SPLIT_MAX_GAP = 20000
_READS_GENOME: frozenset[LengthClass] = frozenset({"SHORT", "SPLIT"})


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


class LengthScreen(CamelModel):
    model_config = ConfigDict(frozen=True)

    genes: list[str]
    length_class: LengthClass
    ratio: float | None
    group_median: float
    group_copies: float
    group_spread: float
    organisms: int
    reference_gene: str | None


class LengthDna(BaseModel):
    model_config = ConfigDict(frozen=True)

    reference_protein: str
    model_proteins: list[str]
    window: DnaWindow
    code: GeneticCode
    code_inferred: bool


class LengthInputs(BaseModel):
    model_config = ConfigDict(frozen=True)

    screen: LengthScreen
    dna: LengthDna | None

    @model_validator(mode="after")
    def _read_when_screened(self) -> Self:
        if (self.dna is not None) != (self.screen.length_class in _READS_GENOME):
            msg = (
                f"a {self.screen.length_class} gene reads the genome only when "
                f"its class is one of {sorted(_READS_GENOME)}"
            )
            raise ValueError(msg)
        return self


class GeneLengthAudit(LengthCheck, LengthScreen):
    code: GeneticCode | None
    code_inferred: bool


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
        reference_model.organism_abbrev,
        reference.sequence_id,
        reference.start,
        reference.end,
    )
    strain_window = await genome.window(
        strain_model.organism_abbrev,
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
        model.organism_abbrev, row.sequence_id, row.start - pad, row.end + pad
    )
    return SelenoproteinInputs(
        model_protein=proteins[gene],
        reference_protein=proteins[reference_gene],
        dna=window.sequence,
        strand=row.strand,
    )


def _pair_refusal(parts: list[GeneRow]) -> ToolErrorPayload | None:
    if len(parts) == 1:
        return None
    first, second = parts
    if first.gene == second.gene:
        return tool_error(
            VEuPathDBErrorCode.VALIDATION_ERROR, f"the pair names {first.gene} twice"
        )
    if (first.organism, first.sequence_id, first.strand) != (
        second.organism,
        second.sequence_id,
        second.strand,
    ):
        return tool_error(
            VEuPathDBErrorCode.VALIDATION_ERROR,
            f"{first.gene} and {second.gene} do not lie on one strand of one sequence",
        )
    gap = max(first.start, second.start) - min(first.end, second.end)
    if gap > SPLIT_MAX_GAP:
        return tool_error(
            VEuPathDBErrorCode.VALIDATION_ERROR,
            f"{first.gene} and {second.gene} lie {gap} bases apart; a split pair "
            f"lies at most {SPLIT_MAX_GAP} bases apart",
        )
    return None


def _screen(parts: list[GeneRow], call: Confirmable | NotChecked) -> LengthScreen:
    return LengthScreen(
        genes=[part.gene for part in parts],
        length_class=call.length_class,
        ratio=call.ratio,
        group_median=call.profile.median,
        group_copies=call.profile.copies,
        group_spread=round(call.profile.spread, 3),
        organisms=call.profile.organisms,
        reference_gene=call.reference.gene if call.reference else None,
    )


def _coding_dna(
    window: GenomeWindow, model: GeneModel, strand: Literal["+", "-"]
) -> str:
    if not all(window.start <= p.start and p.end <= window.end for p in model.cds):
        return ""
    cds = "".join(
        window.sequence[p.start - window.start : p.end - window.start + 1]
        for p in model.cds
    )
    return cds if strand == "+" else reverse_complement(cds)


def _flank(call: Confirmable) -> int:
    missing = call.reference_length - sum(call.lengths)
    return min(
        LENGTH_MAX_FLANK,
        max(LENGTH_MIN_FLANK, missing * LENGTH_FLANK_PER_RESIDUE),
    )


async def _length_dna(
    site_id: str, parts: list[GeneRow], call: Confirmable
) -> LengthDna | ToolErrorPayload:
    genes = [part.gene for part in parts]
    first, last = min(p.start for p in parts), max(p.end for p in parts)
    flank = _flank(call)
    start, end = first - flank, last + flank
    if end - start + 1 > AUDIT_MAX_WINDOW_BASES:
        return _window_refusal(" and ".join(genes), end - start + 1)
    reference = call.reference.gene
    proteins = await proteins_of(site_id, [*genes, reference])
    missing = [gene for gene in (*genes, reference) if gene not in proteins]
    if missing:
        return tool_error(
            VEuPathDBErrorCode.VALIDATION_ERROR,
            f"{', '.join(missing)} has no protein on {site_id}",
        )
    models = [proteins[gene] for gene in genes]
    gene_models = [await gene_model(site_id, gene) for gene in genes]
    abbrev, seqid, strand = (
        gene_models[0].organism_abbrev,
        parts[0].sequence_id,
        parts[0].strand,
    )
    genome = GenomeReader(get_jbrowse_client(site_id))
    contig = await genome.sequence_length(abbrev, seqid)
    window = await genome.window(abbrev, seqid, start, end)
    code = next(
        (
            inferred
            for model, protein in zip(gene_models, models, strict=True)
            if (inferred := infer_code(_coding_dna(window, model, strand), protein))
        ),
        None,
    )
    return LengthDna(
        reference_protein=proteins[reference],
        model_proteins=models,
        window=DnaWindow(
            sequence=window.sequence,
            strand=strand,
            at_contig_edge=first <= LENGTH_EDGE or contig - last <= LENGTH_EDGE,
        ),
        code=code or GeneticCode.STANDARD,
        code_inferred=code is not None,
    )


async def length_inputs(
    site_id: str, genes: list[str]
) -> LengthInputs | ToolErrorPayload:
    if len(genes) not in {1, 2}:
        msg = f"a length check reads one gene or a pair, not {len(genes)}"
        raise ValueError(msg)
    match await _located(site_id, genes):
        case ToolErrorPayload() as refusal:
            return refusal
        case rows:
            parts = [rows[gene] for gene in genes]
    if (unpaired := _pair_refusal(parts)) is not None:
        return unpaired
    match call_length(parts, await orthologs_of(site_id, genes[0])):
        case NotChecked() as call:
            return LengthInputs(screen=_screen(parts, call), dna=None)
        case Confirmable() as call:
            dna = await _length_dna(site_id, parts, call)
    match dna:
        case ToolErrorPayload() as refusal:
            return refusal
        case LengthDna():
            return LengthInputs(screen=_screen(parts, call), dna=dna)

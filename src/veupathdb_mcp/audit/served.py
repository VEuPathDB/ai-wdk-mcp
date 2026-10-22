"""What the served audit checks read from a site, and what each one answers."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator
from veupathdb.errors import VEuPathDBErrorCode
from veupathdb.jbrowse import GenomeReader, GenomeWindow, get_jbrowse_client
from veupathdb.model import CamelModel

from veupathdb_mcp.audit.codes import GeneticCode, infer_code, reverse_complement
from veupathdb_mcp.audit.gene_ids import (
    GeneId,
    GeneReads,
    check_resolved,
    id_pairs,
    rows_and_proteins,
    rows_named,
    several,
)
from veupathdb_mcp.audit.gene_models import GeneModel, gene_model, gene_organism
from veupathdb_mcp.audit.genes import GeneRow, orthologs_of
from veupathdb_mcp.audit.length import DnaWindow, LengthCheck
from veupathdb_mcp.audit.lengths import (
    Confirmable,
    LengthClass,
    NotChecked,
    call_length,
)
from veupathdb_mcp.audit.pseudogene import PseudogeneCheck, ReferenceGene
from veupathdb_mcp.audit.record_reads import record_proteins
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


class PseudogenePair(BaseModel):
    model_config = ConfigDict(frozen=True)

    strain: GeneRow
    reference: GeneRow
    gene_ids: list[GeneId]

    @model_validator(mode="after")
    def _a_flagged_strain(self) -> Self:
        if self.strain.pseudo is not True:
            msg = f"{self.strain.gene} is not flagged a pseudogene"
            raise ValueError(msg)
        check_resolved(self.gene_ids, [self.strain.gene, self.reference.gene])
        return self


class PseudogeneInputs(BaseModel):
    model_config = ConfigDict(frozen=True)

    reference: ReferenceGene
    strain_window: GenomeWindow
    strand: Literal["+", "-"]
    gene_ids: list[GeneId] = Field(min_length=2, max_length=2)

    @property
    def strain_coding_dna(self) -> str:
        dna = self.strain_window.sequence
        return dna if self.strand == "+" else reverse_complement(dna)


class SelenoproteinInputs(BaseModel):
    model_config = ConfigDict(frozen=True)

    model_protein: str
    reference_protein: str
    dna: str
    strand: Literal["+", "-"]
    gene_ids: list[GeneId] = Field(min_length=2, max_length=2)


class LengthScreen(CamelModel):
    model_config = ConfigDict(frozen=True)

    gene_ids: list[GeneId]
    genes: list[str]
    length_class: LengthClass
    ratio: float | None
    group_median: float
    group_copies: float
    group_spread: float
    organisms: int
    reference_gene: str | None

    @model_validator(mode="after")
    def _named_as_resolved(self) -> Self:
        check_resolved(self.gene_ids, self.genes)
        return self


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
    gene_ids: list[GeneId]
    strain_gene: str
    reference_gene: str

    @model_validator(mode="after")
    def _named_as_resolved(self) -> Self:
        check_resolved(self.gene_ids, [self.strain_gene, self.reference_gene])
        return self


class SelenoproteinEndAudit(SecCheck):
    gene_ids: list[GeneId]
    gene: str
    reference_gene: str

    @model_validator(mode="after")
    def _named_as_resolved(self) -> Self:
        check_resolved(self.gene_ids, [self.gene, self.reference_gene])
        return self


def resolved(
    site_id: str, given: list[str], reads: GeneReads
) -> dict[str, GeneRow] | ToolErrorPayload:
    found: dict[str, GeneRow] = {}
    missing: list[str] = []
    for gene in given:
        match reads.named(gene):
            case [row]:
                found[gene] = row
            case []:
                missing.append(gene)
            case named:
                return several(site_id, gene, [row.gene for row in named])
    if missing:
        return tool_error(
            VEuPathDBErrorCode.VALIDATION_ERROR,
            f"{', '.join(missing)} names no gene of {site_id}",
        )
    return found


async def located(
    site_id: str, given: list[str]
) -> dict[str, GeneRow] | ToolErrorPayload:
    match await rows_named(site_id, given):
        case ToolErrorPayload() as refusal:
            return refusal
        case GeneReads() as reads:
            return resolved(site_id, given, reads)


def window_refusal(gene: str, length: int) -> ToolErrorPayload:
    return tool_error(
        VEuPathDBErrorCode.VALIDATION_ERROR,
        f"the {gene} window spans {length} bases; an audit reads at most "
        f"{AUDIT_MAX_WINDOW_BASES} bases of genome per window",
    )


async def read_proteins(
    site_id: str, gene_ids: list[str]
) -> dict[str, str] | ToolErrorPayload:
    proteins = await record_proteins(site_id, gene_ids)
    missing = [gene for gene in gene_ids if gene not in proteins]
    if missing:
        return tool_error(
            VEuPathDBErrorCode.VALIDATION_ERROR,
            f"{', '.join(missing)} has no protein on {site_id}",
        )
    return proteins


def _unflagged(site_id: str, strain: GeneRow) -> ToolErrorPayload | None:
    if strain.pseudo:
        return None
    flag = "No" if strain.pseudo is False else "not served"
    return tool_error(
        VEuPathDBErrorCode.VALIDATION_ERROR,
        f"{strain.gene} is not flagged a pseudogene on {site_id} (is_pseudo: {flag}); "
        "the check reads a strain gene the site calls a pseudogene",
    )


def _span_refusal(strain: GeneRow, reference: GeneRow) -> ToolErrorPayload | None:
    reference_length = reference.end - reference.start + 1
    strain_length = strain.end - strain.start + 1 + 2 * PSEUDOGENE_PAD
    for gene, length in (
        (reference.gene, reference_length),
        (strain.gene, strain_length),
    ):
        if length > AUDIT_MAX_WINDOW_BASES:
            return window_refusal(gene, length)
    if reference_length * strain_length > PSEUDOGENE_MAX_CELLS:
        return tool_error(
            VEuPathDBErrorCode.VALIDATION_ERROR,
            f"{reference.gene} spans {reference_length} bases and the {strain.gene} "
            f"window {strain_length} bases; the check aligns pairs whose product "
            f"is at most {PSEUDOGENE_MAX_CELLS}",
        )
    return None


async def pseudogene_pair(
    site_id: str, strain_gene: str, reference_gene: str
) -> PseudogenePair | ToolErrorPayload:
    match await located(site_id, [strain_gene, reference_gene]):
        case ToolErrorPayload() as refusal:
            return refusal
        case rows:
            strain, reference = rows[strain_gene], rows[reference_gene]
    unread = _unflagged(site_id, strain) or _span_refusal(strain, reference)
    if unread is not None:
        return unread
    return PseudogenePair(
        strain=strain,
        reference=reference,
        gene_ids=id_pairs([strain_gene, reference_gene], rows),
    )


def no_cds(site_id: str, gene: str, model: GeneModel) -> ToolErrorPayload | None:
    if model.cds:
        return None
    return tool_error(
        VEuPathDBErrorCode.VALIDATION_ERROR,
        f"{gene} has no CDS in its gene model on {site_id}",
    )


async def pseudogene_dna(
    site_id: str, pair: PseudogenePair, strain_abbrev: str, reference_model: GeneModel
) -> PseudogeneInputs:
    strain, reference = pair.strain, pair.reference
    genome = GenomeReader(get_jbrowse_client(site_id))
    reference_window = await genome.window(
        reference_model.organism_abbrev,
        reference.sequence_id,
        reference.start,
        reference.end,
    )
    strain_window = await genome.window(
        strain_abbrev,
        strain.sequence_id,
        strain.start - PSEUDOGENE_PAD,
        strain.end + PSEUDOGENE_PAD,
    )
    return PseudogeneInputs(
        reference=ReferenceGene(
            dna=reference_window.sequence,
            cds=reference_model.cds,
            start=reference_window.start,
            end=reference_window.end,
            strand=reference.strand,
        ),
        strain_window=strain_window,
        strand=strain.strand,
        gene_ids=pair.gene_ids,
    )


async def pseudogene_inputs(
    site_id: str, strain_gene: str, reference_gene: str
) -> PseudogeneInputs | ToolErrorPayload:
    match await pseudogene_pair(site_id, strain_gene, reference_gene):
        case ToolErrorPayload() as refusal:
            return refusal
        case PseudogenePair() as pair:
            pass
    reference_model = await gene_model(site_id, pair.reference.gene)
    if (uncoded := no_cds(site_id, pair.reference.gene, reference_model)) is not None:
        return uncoded
    strain_abbrev = await gene_organism(site_id, pair.strain.gene)
    return await pseudogene_dna(site_id, pair, strain_abbrev, reference_model)


def _proteins_of_named(
    site_id: str, named: list[str], reads: GeneReads
) -> dict[str, str] | ToolErrorPayload:
    missing = [gene for gene in named if gene not in reads.proteins]
    if missing:
        return tool_error(
            VEuPathDBErrorCode.VALIDATION_ERROR,
            f"{', '.join(missing)} has no protein on {site_id}",
        )
    return reads.proteins


async def _selenoprotein_reads(
    site_id: str, given: list[str]
) -> tuple[dict[str, GeneRow], dict[str, str]] | ToolErrorPayload:
    match await rows_and_proteins(site_id, given):
        case ToolErrorPayload() as refusal:
            return refusal
        case GeneReads() as reads:
            pass
    match resolved(site_id, given, reads):
        case ToolErrorPayload() as refusal:
            return refusal
        case rows:
            named = [rows[gene].gene for gene in given]
    match _proteins_of_named(site_id, named, reads):
        case ToolErrorPayload() as refusal:
            return refusal
        case proteins:
            return rows, proteins


async def selenoprotein_inputs(
    site_id: str, gene: str, reference_gene: str
) -> SelenoproteinInputs | ToolErrorPayload:
    given = [gene, reference_gene]
    match await _selenoprotein_reads(site_id, given):
        case ToolErrorPayload() as refusal:
            return refusal
        case (rows, proteins):
            row, reference = rows[gene], rows[reference_gene]
    tail = sec_tail(proteins[reference.gene])
    if not tail:
        return tool_error(
            VEuPathDBErrorCode.VALIDATION_ERROR,
            f"{reference.gene} has no selenocysteine on {site_id}",
        )
    pad = SELENOPROTEIN_PAD + 3 * len(tail)
    length = row.end - row.start + 1 + 2 * pad
    if length > AUDIT_MAX_WINDOW_BASES:
        return window_refusal(row.gene, length)
    abbrev = await gene_organism(site_id, row.gene)
    window = await GenomeReader(get_jbrowse_client(site_id)).window(
        abbrev, row.sequence_id, row.start - pad, row.end + pad
    )
    return SelenoproteinInputs(
        model_protein=proteins[row.gene],
        reference_protein=proteins[reference.gene],
        dna=window.sequence,
        strand=row.strand,
        gene_ids=id_pairs(given, rows),
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


def length_screen(
    parts: list[GeneRow], call: Confirmable | NotChecked, ids: list[GeneId]
) -> LengthScreen:
    return LengthScreen(
        gene_ids=ids,
        genes=[part.gene for part in parts],
        length_class=call.length_class,
        ratio=call.ratio,
        group_median=call.profile.median,
        group_copies=call.profile.copies,
        group_spread=round(call.profile.spread, 3),
        organisms=call.profile.organisms,
        reference_gene=call.reference.gene if call.reference else None,
    )


def coding_dna(
    window: GenomeWindow, model: GeneModel, strand: Literal["+", "-"]
) -> str:
    if not all(window.start <= p.start and p.end <= window.end for p in model.cds):
        return ""
    cds = "".join(
        window.sequence[p.start - window.start : p.end - window.start + 1]
        for p in model.cds
    )
    return cds if strand == "+" else reverse_complement(cds)


def length_flank(missing_residues: int) -> int:
    return min(
        LENGTH_MAX_FLANK,
        max(LENGTH_MIN_FLANK, missing_residues * LENGTH_FLANK_PER_RESIDUE),
    )


def length_span(parts: list[GeneRow], missing_residues: int) -> tuple[int, int]:
    flank = length_flank(missing_residues)
    return min(p.start for p in parts) - flank, max(p.end for p in parts) + flank


def length_window(
    parts: list[GeneRow], missing_residues: int
) -> tuple[int, int] | ToolErrorPayload:
    start, end = length_span(parts, missing_residues)
    if end - start + 1 > AUDIT_MAX_WINDOW_BASES:
        genes = " and ".join(part.gene for part in parts)
        return window_refusal(genes, end - start + 1)
    return start, end


async def length_dna(
    site_id: str,
    parts: list[GeneRow],
    span: tuple[int, int],
    reference_protein: str,
    model_proteins: list[str],
) -> LengthDna:
    first, last = min(p.start for p in parts), max(p.end for p in parts)
    gene_models = [await gene_model(site_id, part.gene) for part in parts]
    abbrev, seqid, strand = (
        gene_models[0].organism_abbrev,
        parts[0].sequence_id,
        parts[0].strand,
    )
    genome = GenomeReader(get_jbrowse_client(site_id))
    contig = await genome.sequence_length(abbrev, seqid)
    window = await genome.window(abbrev, seqid, *span)
    code = next(
        (
            inferred
            for model, protein in zip(gene_models, model_proteins, strict=True)
            if (inferred := infer_code(coding_dna(window, model, strand), protein))
        ),
        None,
    )
    return LengthDna(
        reference_protein=reference_protein,
        model_proteins=model_proteins,
        window=DnaWindow(
            sequence=window.sequence,
            strand=strand,
            at_contig_edge=first <= LENGTH_EDGE or contig - last <= LENGTH_EDGE,
        ),
        code=code or GeneticCode.STANDARD,
        code_inferred=code is not None,
    )


async def _confirmed_dna(
    site_id: str, parts: list[GeneRow], call: Confirmable
) -> LengthDna | ToolErrorPayload:
    match length_window(parts, call.reference_length - sum(call.lengths)):
        case ToolErrorPayload() as refusal:
            return refusal
        case span:
            pass
    genes = [part.gene for part in parts]
    match await read_proteins(site_id, [*genes, call.reference.gene]):
        case ToolErrorPayload() as refusal:
            return refusal
        case proteins:
            models = [proteins[gene] for gene in genes]
    return await length_dna(site_id, parts, span, proteins[call.reference.gene], models)


async def length_inputs(
    site_id: str, genes: list[str]
) -> LengthInputs | ToolErrorPayload:
    if len(genes) not in {1, 2}:
        msg = f"a length check reads one gene or a pair, not {len(genes)}"
        raise ValueError(msg)
    match await located(site_id, genes):
        case ToolErrorPayload() as refusal:
            return refusal
        case rows:
            parts = [rows[gene] for gene in genes]
            ids = id_pairs(genes, rows)
    if (unpaired := _pair_refusal(parts)) is not None:
        return unpaired
    group = await orthologs_of(site_id, parts[0].gene)
    match call_length(parts, group.members):
        case NotChecked() as call:
            return LengthInputs(screen=length_screen(parts, call, ids), dna=None)
        case Confirmable() as call:
            dna = await _confirmed_dna(site_id, parts, call)
    match dna:
        case ToolErrorPayload() as refusal:
            return refusal
        case LengthDna():
            return LengthInputs(screen=length_screen(parts, call, ids), dna=dna)

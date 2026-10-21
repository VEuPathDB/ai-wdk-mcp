"""What the intron support check reads from a site: the gene's model and the junctions
of every RNA-seq junction track over it, then, for a correction, its genome and protein."""

from __future__ import annotations

import weakref

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from veupathdb.errors import DataParsingError
from veupathdb.jbrowse import (
    GenomeReader,
    GenomeWindow,
    JBrowseClient,
    SequenceNotIndexedError,
    TabixReader,
    get_jbrowse_client,
    parse_gff_line,
)

from veupathdb_mcp.audit.codes import GeneticCode, infer_code
from veupathdb_mcp.audit.gene_ids import GeneId, id_pairs
from veupathdb_mcp.audit.gene_models import (
    MODEL_TABLE,
    GeneModel,
    ModelRow,
    model_record,
    transcript_spans,
)
from veupathdb_mcp.audit.genes import GeneRow, OrthologRow, ortholog_table, proteins_of
from veupathdb_mcp.audit.introns import GeneStructure, RnaJunction, Span
from veupathdb_mcp.audit.introns_orthologs import OrthologProtein, OrthologSet
from veupathdb_mcp.audit.lengths import species_of
from veupathdb_mcp.audit.served import (
    AUDIT_MAX_WINDOW_BASES,
    coding_dna,
    located,
    read_proteins,
    window_refusal,
)
from veupathdb_mcp.tool_errors import ToolErrorPayload

INTRON_READ_THROUGH = 3000
INTRON_JUNCTION_PAD = 200
ORTHOLOGS_READ = 60


class UncheckedIntrons(BaseModel):
    model_config = ConfigDict(frozen=True)

    gene_ids: list[GeneId] = Field(min_length=1, max_length=1)
    reason: str
    transcript: str | None = None
    other_transcripts: int | None = None
    tracks_refused: list[str] | None = None


class _TrackReads(BaseModel):
    model_config = ConfigDict(frozen=True)

    junctions: list[RnaJunction]
    refused: list[str]


class _NoTrack(BaseModel):
    model_config = ConfigDict(frozen=True)

    reason: str
    refused: list[str] | None


class IntronReads(BaseModel):
    model_config = ConfigDict(frozen=True)

    gene_ids: list[GeneId] = Field(min_length=1, max_length=1)
    row: GeneRow
    model: GeneModel
    structure: GeneStructure
    junctions: list[RnaJunction]
    tracks_refused: list[str]


class CorrectionInputs(BaseModel):
    model_config = ConfigDict(frozen=True)

    dna: GenomeWindow
    protein: str
    code: GeneticCode
    code_inferred: bool


def junction_region(row: GeneRow) -> Span:
    return max(1, row.start - INTRON_JUNCTION_PAD), row.end + INTRON_JUNCTION_PAD


def genome_region(row: GeneRow) -> Span:
    return max(1, row.start - INTRON_READ_THROUGH), row.end + INTRON_READ_THROUGH


def ortholog_species(table: list[OrthologRow], row: GeneRow) -> dict[str, str]:
    own = species_of(row.organism)
    named: dict[str, str] = {}
    for ortholog in table:
        species = species_of(ortholog.organism)
        if ortholog.gene != row.gene and species != own and ortholog.gene not in named:
            named[ortholog.gene] = species
    return dict(list(named.items())[:ORTHOLOGS_READ])


def _structure(rows: list[ModelRow], model: GeneModel, row: GeneRow) -> GeneStructure:
    cds = [(part.start, part.end) for part in model.cds]
    transcripts = {transcript for r in rows for transcript in r.transcript_ids}
    main = min(t for t in transcripts if transcript_spans(rows, "CDS", t) == cds)
    try:
        return GeneStructure(
            transcript=main,
            other_transcripts=len(transcripts) - 1,
            strand=row.strand,
            start=row.start,
            end=row.end,
            exons=transcript_spans(rows, "Exon", main),
            cds=cds,
        )
    except ValidationError as exc:
        msg = (
            f"the {MODEL_TABLE} of {row.gene} gives no Exon row for {main} in the gene"
        )
        raise DataParsingError(msg) from exc


def _features(lines: list[str], path: str) -> list[RnaJunction]:
    try:
        return [RnaJunction.from_feature(parse_gff_line(line), path) for line in lines]
    except ValidationError as exc:
        msg = f"a junction of {path} gives no readable totalscore or evidence"
        raise DataParsingError(msg) from exc


_READERS: weakref.WeakKeyDictionary[JBrowseClient, TabixReader] = (
    weakref.WeakKeyDictionary()
)


def _tabix_reader(client: JBrowseClient) -> TabixReader:
    if client not in _READERS:
        _READERS[client] = TabixReader(client)
    return _READERS[client]


async def _junctions(
    site_id: str, client: JBrowseClient, abbrev: str, row: GeneRow
) -> _TrackReads | _NoTrack:
    tracks = await client.junction_tracks(abbrev)
    if not tracks:
        return _NoTrack(
            reason=f"{site_id} lists no RNA-seq junction track for {abbrev}",
            refused=None,
        )
    start, end = junction_region(row)
    reader = _tabix_reader(client)
    found: list[RnaJunction] = []
    refused: list[str] = []
    for track in tracks:
        try:
            lines = await reader.lines(track, row.sequence_id, start, end)
        except SequenceNotIndexedError as exc:
            refused.append(exc.detail or exc.title)
            continue
        found += _features(lines, track.data_path)
    if len(refused) == len(tracks):
        return _NoTrack(reason="; ".join(refused), refused=refused)
    return _TrackReads(junctions=found, refused=refused)


async def _read_junctions(
    site_id: str,
    ids: list[GeneId],
    row: GeneRow,
    model: GeneModel,
    structure: GeneStructure,
) -> IntronReads | UncheckedIntrons:
    client = get_jbrowse_client(site_id)
    match await _junctions(site_id, client, model.organism_abbrev, row):
        case _NoTrack() as missing:
            return UncheckedIntrons(
                gene_ids=ids,
                reason=missing.reason,
                transcript=structure.transcript,
                other_transcripts=structure.other_transcripts,
                tracks_refused=missing.refused,
            )
        case _TrackReads() as read:
            return IntronReads(
                gene_ids=ids,
                row=row,
                model=model,
                structure=structure,
                junctions=read.junctions,
                tracks_refused=read.refused,
            )


async def intron_inputs(
    site_id: str, gene: str
) -> IntronReads | UncheckedIntrons | ToolErrorPayload:
    match await located(site_id, [gene]):
        case ToolErrorPayload() as refusal:
            return refusal
        case rows:
            row = rows[gene]
            ids = id_pairs([gene], rows)
    length = row.end - row.start + 1 + 2 * INTRON_READ_THROUGH
    if length > AUDIT_MAX_WINDOW_BASES:
        return window_refusal(row.gene, length)
    record = await model_record(site_id, row.gene)
    model = record.model
    if not model.cds:
        return UncheckedIntrons(
            gene_ids=ids,
            reason=f"{row.gene} has no CDS in its gene model on {site_id}",
        )
    structure = _structure(record.rows, model, row)
    if not structure.introns:
        return UncheckedIntrons(
            gene_ids=ids,
            reason=f"{row.gene} has no annotated intron on {site_id}",
            transcript=structure.transcript,
            other_transcripts=structure.other_transcripts,
        )
    return await _read_junctions(site_id, ids, row, model, structure)


async def correction_inputs(
    site_id: str, reads: IntronReads
) -> CorrectionInputs | ToolErrorPayload:
    row = reads.row
    match await read_proteins(site_id, [row.gene]):
        case ToolErrorPayload() as refusal:
            return refusal
        case proteins:
            protein = proteins[row.gene]
    start, end = genome_region(row)
    window = await GenomeReader(get_jbrowse_client(site_id)).window(
        reads.model.organism_abbrev, row.sequence_id, start, end
    )
    code = infer_code(coding_dna(window, reads.model, row.strand), protein)
    return CorrectionInputs(
        dna=window,
        protein=protein,
        code=code or GeneticCode.STANDARD,
        code_inferred=code is not None,
    )


async def ortholog_proteins(site_id: str, row: GeneRow) -> OrthologSet:
    named = ortholog_species(await ortholog_table(site_id, row.gene), row)
    proteins = await proteins_of(site_id, list(named))
    return OrthologSet(
        named=len(named),
        proteins=[
            OrthologProtein(gene=gene, species=species, protein=proteins[gene])
            for gene, species in named.items()
            if gene in proteins
        ],
    )

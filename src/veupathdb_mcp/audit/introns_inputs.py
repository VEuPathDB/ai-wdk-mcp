"""What the intron support check reads from a site: the gene's model and the junctions
of every RNA-seq junction track over it, the staged evidence for an intron no junction
reads, then, for a correction, its genome, its protein and its orthologs' proteins."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from veupathdb.errors import DataParsingError
from veupathdb.jbrowse import (
    GenomeWindow,
    JBrowseClient,
    SequenceNotIndexedError,
    get_jbrowse_client,
    parse_gff_line,
)

from veupathdb_mcp.audit.codes import GeneticCode, infer_code
from veupathdb_mcp.audit.gene_ids import GeneId, id_pairs
from veupathdb_mcp.audit.gene_models import (
    GeneModel,
    ModelRecord,
    ReadModels,
    TranscriptParts,
    model_record,
    no_exon_row,
    transcript_parts,
)
from veupathdb_mcp.audit.genes import GeneRow, GroupMember, OrthologGroup, orthologs_of
from veupathdb_mcp.audit.intron_evidence import (
    StagedEvidence,
    stage_evidence,
)
from veupathdb_mcp.audit.introns import (
    JUNCTION_TRACKS_READ,
    NO_EVIDENCE,
    GeneStructure,
    IntronEvidence,
    JunctionTracks,
    RnaJunction,
    Span,
)
from veupathdb_mcp.audit.introns_orthologs import OrthologProtein, OrthologSet
from veupathdb_mcp.audit.lengths import species_of
from veupathdb_mcp.audit.record_reads import record_proteins
from veupathdb_mcp.audit.served import (
    AUDIT_MAX_WINDOW_BASES,
    coding_dna,
    located,
    read_proteins,
    window_refusal,
)
from veupathdb_mcp.audit.track_reads import (
    GeneSite,
    genome_reader,
    tabix_reader,
)
from veupathdb_mcp.tool_errors import ToolErrorPayload

INTRON_READ_THROUGH = 3000
INTRON_JUNCTION_PAD = 200
ORTHOLOG_PROTEINS_READ = 16


class UncheckedIntrons(BaseModel):
    model_config = ConfigDict(frozen=True)

    gene_ids: list[GeneId] = Field(min_length=1, max_length=1)
    reason: str
    transcript: str | None = None
    other_transcripts: int | None = None
    tracks_refused: list[str] | None = None
    junction_tracks: JunctionTracks | None = None
    evidence_unread: list[str] = Field(default_factory=list)


class _TrackReads(BaseModel):
    model_config = ConfigDict(frozen=True)

    junctions: list[RnaJunction]
    refused: list[str]
    tracks: JunctionTracks


class _NoTrack(BaseModel):
    model_config = ConfigDict(frozen=True)

    reason: str
    refused: list[str] | None
    tracks: JunctionTracks


class IntronReads(BaseModel):
    model_config = ConfigDict(frozen=True)

    gene_ids: list[GeneId] = Field(min_length=1, max_length=1)
    row: GeneRow
    model: GeneModel
    models: ReadModels
    structure: GeneStructure
    junctions: list[RnaJunction]
    tracks_refused: list[str]
    junction_tracks: JunctionTracks
    evidence: IntronEvidence = NO_EVIDENCE
    window: GenomeWindow | None = None
    evidence_unread: list[str] = Field(default_factory=list)


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


def _nearest(members: list[GroupMember], length: int) -> GroupMember:
    return min(members, key=lambda m: abs((m.protein_length or 0) - length))


def ortholog_choice(group: OrthologGroup, row: GeneRow) -> dict[str, str]:
    own = species_of(row.organism)
    by_species: dict[str, list[GroupMember]] = {}
    for member in group.members:
        species = species_of(member.organism)
        if member.gene != row.gene and species != own and member.protein_length:
            by_species.setdefault(species, []).append(member)
    named: dict[str, str] = {}
    for species, members in by_species.items():
        reference = next((m for m in members if m.reference_strain), None)
        for chosen in (reference, _nearest(members, row.protein_length or 0)):
            if chosen is not None and len(named) < ORTHOLOG_PROTEINS_READ:
                named.setdefault(chosen.gene, species)
    return named


def _structure(
    record: ModelRecord, parts: TranscriptParts, row: GeneRow
) -> GeneStructure:
    if not parts.exons:
        raise DataParsingError(no_exon_row(row.gene, parts.transcript))
    transcripts = {t for r in record.rows for t in r.transcript_ids}
    try:
        return GeneStructure(
            transcript=parts.transcript,
            other_transcripts=len(transcripts) - 1,
            strand=row.strand,
            start=row.start,
            end=row.end,
            exons=parts.exons,
            cds=parts.cds,
        )
    except ValidationError as exc:
        msg = f"the model of {row.gene} has a part outside the gene's span"
        raise DataParsingError(msg) from exc


def _features(lines: list[str], path: str) -> list[RnaJunction]:
    try:
        return [RnaJunction.from_feature(parse_gff_line(line), path) for line in lines]
    except ValidationError as exc:
        msg = f"a junction of {path} gives no readable totalscore or evidence"
        raise DataParsingError(msg) from exc


async def _junctions(
    site_id: str, client: JBrowseClient, abbrev: str, row: GeneRow
) -> _TrackReads | _NoTrack:
    listed = await client.junction_tracks(abbrev)
    tracks = listed[:JUNCTION_TRACKS_READ]
    counted = JunctionTracks(
        organism_abbrev=abbrev,
        listed=len(listed),
        read=min(len(listed), JUNCTION_TRACKS_READ),
    )
    if not tracks:
        return _NoTrack(
            reason=f"{site_id} lists no RNA-seq junction track for {abbrev}",
            refused=None,
            tracks=counted,
        )
    start, end = junction_region(row)
    reader = tabix_reader(client)
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
        return _NoTrack(reason="; ".join(refused), refused=refused, tracks=counted)
    return _TrackReads(junctions=found, refused=refused, tracks=counted)


async def _staged(
    client: JBrowseClient,
    row: GeneRow,
    model: GeneModel,
    structure: GeneStructure,
    junctions: list[RnaJunction],
) -> StagedEvidence:
    gene = GeneSite(
        abbrev=model.organism_abbrev,
        seqid=row.sequence_id,
        start=row.start,
        end=row.end,
        strand=row.strand,
        window=genome_region(row),
    )
    return await stage_evidence(client, gene, structure, junctions)


async def _read_junctions(
    site_id: str,
    ids: list[GeneId],
    row: GeneRow,
    record: ModelRecord,
    structure: GeneStructure,
) -> IntronReads | UncheckedIntrons:
    model = record.model
    client = get_jbrowse_client(site_id)
    match await _junctions(site_id, client, model.organism_abbrev, row):
        case _NoTrack() as missing:
            return UncheckedIntrons(
                gene_ids=ids,
                reason=missing.reason,
                transcript=structure.transcript,
                other_transcripts=structure.other_transcripts,
                tracks_refused=missing.refused,
                junction_tracks=missing.tracks,
                evidence_unread=list(filter(None, [missing.tracks.cap_note])),
            )
        case _TrackReads() as read:
            staged = await _staged(client, row, model, structure, read.junctions)
            return IntronReads(
                gene_ids=ids,
                row=row,
                model=model,
                models=ReadModels.of([record]),
                structure=structure,
                junctions=read.junctions,
                tracks_refused=read.refused,
                junction_tracks=read.tracks,
                evidence=staged.evidence,
                window=staged.window,
                evidence_unread=[
                    *filter(None, [read.tracks.cap_note]),
                    *staged.unread,
                ],
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
    parts = transcript_parts(record.rows)
    if parts is None:
        return UncheckedIntrons(
            gene_ids=ids,
            reason=f"{row.gene} has no CDS in its gene model on {site_id}",
        )
    structure = _structure(record, parts, row)
    if not structure.introns:
        return UncheckedIntrons(
            gene_ids=ids,
            reason=f"{row.gene} has no annotated intron on {site_id}",
            transcript=structure.transcript,
            other_transcripts=structure.other_transcripts,
        )
    return await _read_junctions(site_id, ids, row, record, structure)


async def correction_inputs(
    site_id: str, reads: IntronReads
) -> CorrectionInputs | ToolErrorPayload:
    row = reads.row
    match await read_proteins(site_id, [row.gene]):
        case ToolErrorPayload() as refusal:
            return refusal
        case proteins:
            protein = proteins[row.gene]
    window = reads.window or await genome_reader(get_jbrowse_client(site_id)).window(
        reads.model.organism_abbrev, row.sequence_id, *genome_region(row)
    )
    code = infer_code(coding_dna(window, reads.model, row.strand), protein)
    return CorrectionInputs(
        dna=window,
        protein=protein,
        code=code or GeneticCode.STANDARD,
        code_inferred=code is not None,
    )


async def ortholog_proteins(site_id: str, row: GeneRow) -> OrthologSet:
    named = ortholog_choice(await orthologs_of(site_id, row.gene), row)
    proteins = await record_proteins(site_id, list(named))
    return OrthologSet(
        named=len(named),
        proteins=[
            OrthologProtein(gene=gene, species=species, protein=proteins[gene])
            for gene, species in named.items()
            if gene in proteins
        ],
    )

"""What explains an annotated intron no junction reads, read from the site's JBrowse
store in stages: peptides split across it, its splice motif, and its read depth."""

from __future__ import annotations

from itertools import pairwise

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from veupathdb.errors import DataParsingError
from veupathdb.jbrowse import (
    GenomeWindow,
    JBrowseClient,
    SequenceNotIndexedError,
    TrackConfig,
    parse_gff_line,
)

from veupathdb_mcp.audit.codes import reverse_complement
from veupathdb_mcp.audit.intron_coverage import (
    BIGWIG_READS_PER_DEPTH,
    COVERAGE_CANDIDATE_PAIRS,
    read_depth,
)
from veupathdb_mcp.audit.intron_judge import (
    judge_introns,
    needs_depth,
    needs_motifs,
    needs_peptides,
)
from veupathdb_mcp.audit.introns import (
    NO_EVIDENCE,
    GeneStructure,
    IntronEvidence,
    PeptideSplit,
    RnaJunction,
    Span,
    Strand,
    intron_key,
)
from veupathdb_mcp.audit.track_reads import (
    READ_FAILURES,
    GeneSite,
    failed_read,
    genome_reader,
    organism_tracks,
    tabix_reader,
    tabix_track,
)

PEPTIDE_TRACK = "unifiedGenomicMassSpec"
PEPTIDE_MAX_GROUPS = 2
INTRON_STORE_READS = (
    1 + PEPTIDE_MAX_GROUPS + COVERAGE_CANDIDATE_PAIRS * 2 * BIGWIG_READS_PER_DEPTH
)
GENOME_BASES = frozenset("ACGT")


class _PeptideTags(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    parent: tuple[str, ...] = Field(default=(), validation_alias="Parent")
    own: tuple[str, ...] = Field(default=(), validation_alias="ID")


class _Segment(BaseModel):
    model_config = ConfigDict(frozen=True)

    span: Span
    strand: str
    tags: _PeptideTags


class StagedEvidence(BaseModel):
    model_config = ConfigDict(frozen=True)

    evidence: IntronEvidence
    window: GenomeWindow | None
    unread: list[str]


async def peptide_track(client: JBrowseClient, abbrev: str) -> TrackConfig | None:
    return tabix_track(await organism_tracks(client, abbrev), PEPTIDE_TRACK)


def _segments(lines: list[str]) -> list[_Segment]:
    try:
        features = [parse_gff_line(line) for line in lines]
        return [
            _Segment(
                span=(f.start, f.end),
                strand=f.strand,
                tags=_PeptideTags.model_validate(f.attributes),
            )
            for f in features
        ]
    except ValidationError as exc:
        msg = "a genomic peptide line is not a readable GFF feature"
        raise DataParsingError(msg) from exc


def peptide_splits(lines: list[str], strand: Strand) -> tuple[PeptideSplit, ...]:
    segments = [s for s in _segments(lines) if s.strand == strand]
    parented = [s for s in segments if s.tags.parent]
    groups: dict[str, list[Span]] = {}
    for found in parented or segments:
        named = found.tags.parent or found.tags.own
        if named:
            groups.setdefault(named[0], []).append(found.span)
    return tuple(
        PeptideSplit(before=before, after=after)
        for segments in groups.values()
        for before, after in pairwise(sorted(set(segments)))
        if before[1] < after[0]
    )


async def _peptides(
    client: JBrowseClient, gene: GeneSite
) -> tuple[PeptideSplit, ...] | str:
    track = await peptide_track(client, gene.abbrev)
    if track is None:
        return f"{gene.abbrev} lists no {PEPTIDE_TRACK} track"
    reader = tabix_reader(client)
    try:
        groups = await reader.chunk_group_count(track, gene.seqid, gene.start, gene.end)
    except SequenceNotIndexedError:
        return ()
    if groups > PEPTIDE_MAX_GROUPS:
        return (
            f"the peptides over {gene.seqid}:{gene.start}-{gene.end} lie in "
            f"{groups} chunk groups; at most {PEPTIDE_MAX_GROUPS} are read"
        )
    lines = await reader.lines(track, gene.seqid, gene.start, gene.end)
    return peptide_splits(lines, gene.strand)


async def read_peptides(
    client: JBrowseClient, gene: GeneSite
) -> tuple[PeptideSplit, ...] | str:
    try:
        return await _peptides(client, gene)
    except READ_FAILURES as exc:
        return failed_read("peptide reads", exc)


def splice_motif(window: GenomeWindow, intron: Span, strand: Strand) -> str | None:
    start, end = intron
    if not window.start <= start < end <= window.end:
        return None
    first = window.sequence[start - window.start : start - window.start + 2]
    last = window.sequence[end - window.start - 1 : end - window.start + 1]
    if strand == "-":
        first, last = reverse_complement(last), reverse_complement(first)
    return f"{first}..{last}".upper()


def spans_gap(motif: str) -> bool:
    return not set(motif.replace("..", "")) <= GENOME_BASES


async def stage_evidence(
    client: JBrowseClient,
    gene: GeneSite,
    structure: GeneStructure,
    junctions: list[RnaJunction],
) -> StagedEvidence:
    evidence = NO_EVIDENCE
    window: GenomeWindow | None = None
    unread: list[str] = []
    judgement = judge_introns(structure, junctions)
    if needs_peptides(judgement):
        match await read_peptides(client, gene):
            case str() as reason:
                unread.append(reason)
            case peptides:
                evidence = IntronEvidence(peptides=peptides)
                judgement = judge_introns(structure, junctions, evidence)
    if spans := needs_motifs(judgement):
        try:
            window = await genome_reader(client).window(
                gene.abbrev, gene.seqid, *gene.window
            )
        except READ_FAILURES as exc:
            unread.append(failed_read("genome window read", exc))
        read = (
            {}
            if window is None
            else {span: splice_motif(window, span, structure.strand) for span in spans}
        )
        motifs = {
            intron_key(span): motif for span, motif in read.items() if motif is not None
        }
        evidence = IntronEvidence(
            peptides=evidence.peptides,
            motifs={k: m for k, m in motifs.items() if not spans_gap(m)},
            gaps=tuple(k for k, m in motifs.items() if spans_gap(m)),
        )
        judgement = judge_introns(structure, junctions, evidence)
        unread += [
            note for u in judgement.unread or [] if (note := u.assembly_gap_note)
        ]
    if spans := needs_depth(judgement):
        found = await read_depth(client, gene, structure.exons, spans)
        unread += found.notes
        if found.depth is not None:
            evidence = IntronEvidence(
                peptides=evidence.peptides,
                motifs=evidence.motifs,
                gaps=evidence.gaps,
                depth=found.depth,
            )
    return StagedEvidence(evidence=evidence, window=window, unread=unread)

"""The served intron support check, read from the site the call names."""

from __future__ import annotations

import httpx
from veupathdb.errors import VEuPathDBError

from veupathdb_mcp.audit.genes import GeneRow
from veupathdb_mcp.audit.intron_judge import (
    judge_introns,
)
from veupathdb_mcp.audit.introns import (
    CORRECTABLE,
    IntronAudit,
    IntronJudgement,
    UnreadIntron,
)
from veupathdb_mcp.audit.introns_correction import IntronCorrection, correct_model
from veupathdb_mcp.audit.introns_inputs import (
    CorrectionInputs,
    IntronReads,
    UncheckedIntrons,
    correction_inputs,
    intron_inputs,
    ortholog_proteins,
)
from veupathdb_mcp.audit.introns_orthologs import OrthologSupport, ortholog_support
from veupathdb_mcp.audit.lengths import is_orthology_group
from veupathdb_mcp.tool_errors import ToolErrorPayload
from veupathdb_mcp.tools.audit_tools import read_inputs, run_in_a_slot, site_failure


async def _orthologs(
    site_id: str, row: GeneRow, annotated: str, corrected: str
) -> OrthologSupport:
    if not is_orthology_group(row.ortholog_group):
        return OrthologSupport.not_read(
            f"the ortholog group {row.ortholog_group} of {row.gene} is not an "
            "orthology group"
        )
    try:
        found = await ortholog_proteins(site_id, row)
    except (VEuPathDBError, httpx.HTTPError) as exc:
        return OrthologSupport.not_read(site_failure(site_id, exc, "ortholog reads"))
    return await run_in_a_slot(ortholog_support, annotated, corrected, found)


def _unchecked(unchecked: UncheckedIntrons) -> IntronAudit:
    return IntronAudit.model_validate(
        {
            **IntronJudgement.not_checked(unchecked.reason).model_dump(),
            "gene_ids": unchecked.gene_ids,
            "gene": unchecked.gene_ids[0].resolved,
            "transcript": unchecked.transcript,
            "other_transcripts": unchecked.other_transcripts,
            "tracks_refused": unchecked.tracks_refused,
            "junction_tracks": unchecked.junction_tracks,
            "evidence_unread": unchecked.evidence_unread,
            "corrected_cds": None,
            "corrected_protein": None,
            "frame_kept": None,
            "code": None,
            "code_inferred": False,
            "orthologs": None,
        }
    )


async def _correction(
    site_id: str, reads: IntronReads, unread: list[UnreadIntron]
) -> tuple[CorrectionInputs, IntronCorrection] | str:
    try:
        match await correction_inputs(site_id, reads):
            case ToolErrorPayload() as refusal:
                return refusal.message
            case CorrectionInputs() as inputs:
                correction = await run_in_a_slot(
                    correct_model, reads.structure, unread, inputs.dna, inputs.code
                )
    except (VEuPathDBError, httpx.HTTPError) as exc:
        return site_failure(site_id, exc, "correction reads")
    return inputs, correction


async def _judged(site_id: str, reads: IntronReads) -> IntronAudit:
    structure = reads.structure
    judgement = await run_in_a_slot(
        judge_introns, structure, reads.junctions, reads.evidence
    )
    audit = {
        **judgement.model_dump(),
        "gene_ids": reads.gene_ids,
        "gene": reads.row.gene,
        "transcript": structure.transcript,
        "other_transcripts": structure.other_transcripts,
        "tracks_refused": reads.tracks_refused,
        "junction_tracks": reads.junction_tracks,
        "evidence_unread": [*reads.evidence_unread, *reads.models.evidence_unread],
        "corrected_cds": None,
        "corrected_protein": None,
        "frame_kept": None,
        "code": None,
        "code_inferred": False,
        "orthologs": None,
        "model": reads.models.models[0],
    }
    if judgement.verdict not in CORRECTABLE or judgement.unread is None:
        return IntronAudit.model_validate(audit)
    match await _correction(site_id, reads, judgement.unread):
        case str() as reason:
            return IntronAudit.model_validate({**audit, "correction_reason": reason})
        case (inputs, correction):
            pass
    orthologs = await _orthologs(site_id, reads.row, inputs.protein, correction.protein)
    return IntronAudit.model_validate(
        {
            **audit,
            "corrected_cds": correction.cds,
            "corrected_protein": correction.protein,
            "frame_kept": correction.frame_kept,
            "code": inputs.code,
            "code_inferred": inputs.code_inferred,
            "orthologs": orthologs,
        }
    )


async def audit_intron_support(site_id: str, gene: str) -> IntronAudit:
    """Check whether RNA-seq reads support each annotated intron of a gene model.

    Only the transcript with the longest CDS is judged (transcript); the
    gene's other transcripts are counted (otherTranscripts), not judged.
    The first 4 RNA-seq junction tracks the site serves for the gene's
    organism are read over the gene; junctionTracks gives how many the
    organism lists (listed) and how many were read (read), and
    evidenceUnread names the cut when listed is past read. junctionTracks
    is null when the call ends before the track list is read. Junctions
    with no strand are set aside and counted (unstrandedIgnored). bestJunctionReads is what the expression gate
    measured: the reads of the best annotated intron, or, when no annotated
    intron has a read, of the best Strong Evidence junction on the gene's
    strand that lies wholly inside the gene. The gene is NOT_EXPRESSED when
    that is under 50 reads, and then no intron is judged and unread is null.
    Each annotated intron of 20 bases or more with no read is judged in
    stages, each read only while an intron is left UNEXPLAINED, and is
    listed in unread with inCds and its outcome, unless the junctions leave
    it UNEXPLAINED and a genomic peptide split across it (one peptide with
    a segment on each side whose gap is the intron within 3 bases, on the
    gene's strand) supports it. Outcomes,
    in order: SHIFTED when one strong junction (Strong Evidence, 20 reads or
    more) starts and ends within 30 bases of it; MISSING_EXON when a chain
    of two or more strong junctions spans it; REPLACED when a strong
    same-strand junction inside the gene overlaps it, ends more than 30
    bases from it at either end and has at least 0.25 of the median reads
    of the gene's read introns (the most-read one is replacement[0]);
    NONCANONICAL when its motif (first two and last two bases on the gene's
    strand, as "GT..AG") is neither GT..AG nor GC..AG; RETAINED when its
    median per-base RNA-seq depth is at least 0.25 of the median depth over
    the gene's exons, at least 0.9 of its bases have a read
    (coveredShare), and every other intron has 20 reads or more or a
    peptide supports it;
    UNEXPLAINED otherwise, an intron whose evidence was not read included.
    A motif holding a base other than A, C, G or T means the intron spans an
    assembly gap: its motif and depth are not read, spansAssemblyGap is true
    (false for every other intron) whatever outcome its junctions give, and
    evidenceUnread names it; one left UNEXPLAINED corrects no model.
    motif and depth are set whenever their stage read the intron; depth
    names the coverage subtrack read (track), its intronMedianDepth,
    exonMedianDepth, coveredShare and depthShare. evidenceUnread says which stage could
    not be read, and why: a track list, peptide, genome window, header or
    depth read the site refuses or fails is named with its status, leaves
    that stage unread and does not fail the call; a refused header drops
    only its pair from the shortlist. The verdict is the first of UNSUPPORTED_UNEXPLAINED,
    UNSUPPORTED_NONCANONICAL, UNSUPPORTED_RETAINED, UNSUPPORTED_MISSING_EXON,
    UNSUPPORTED_REPLACED and UNSUPPORTED_SHIFTED any unread intron gives;
    SUPPORTED means no unread intron. Only when no unread intron is
    UNEXPLAINED is one model corrected from them all and read from the
    genome: SHIFTED, MISSING_EXON and REPLACED introns join the exons with
    their junctions cut out, NONCANONICAL and RETAINED ones are read as
    exon. correctedCds (parts in ascending genome order, the stop codon
    included) and correctedProtein are translated with the genetic code the
    gene's own CDS and protein show (the standard code when codeInferred is
    false), and the orthologs count: per species other than the gene's own,
    in the ortholog table's order, its reference-strain member and the
    member whose protein length is nearest the gene's, up to 16 genes
    (named; read is how many served a protein); the closest copy in each of
    up to 8 species; and how many of them hold more 20-residue windows only
    the corrected protein has (forCorrected) or only the annotated one has
    (forAnnotated); reason says why there is no count. When the protein or
    the genome window for the correction cannot be read, the verdict and
    unread stay, the corrected fields, code and orthologs are null, and
    correctionReason says why. tracksRefused lists the junction tracks that
    do not index the gene's sequence, and is null when no track was read.
    model gives the judged transcript's exon and CDS spans (genome coordinates, 1-based, inclusive, ascending), its seqid and strand; it is null for a
    NOT_CHECKED answer, and null when the model's rows lie on more than one
    sequence or strand, with evidenceUnread giving why. A model with no Exon
    row for the judged transcript is refused.
    NOT_CHECKED, with its reason, means the gene has no CDS or intron, the
    organism has no junction track, no track indexes the gene's sequence,
    or every junction over the gene has no strand; then introns and unread
    are null. A missing input of this kind is a NOT_CHECKED answer, not a
    tool error.
    Reads: the record of the id and its gene model (one gene record read
    each); up to 4 junction tracks' tabix indexes and the chunks over the
    gene.
    The peptide stage reads the organism's track list (shared with
    concurrent checks of the organism) and the
    unifiedGenomicMassSpec index (once per organism and process) and at
    most 2 chunk groups over the gene; more groups leave it unread. The
    motif stage reads one genome window (the gene with 3,000 bases on each
    side, reused by the correction), and the FASTA index once per organism
    and process. The coverage stage, the first time a gene of an organism
    reaches it in a process, reads the organism's RNA-seq track list and
    the total-summary header of every stranded coverage file (at most 200,
    the first in track-label order past that, as evidenceUnread says), and
    keeps the choice for the process; a track list the site refuses is
    named in evidenceUnread and read again by the organism's next gene;
    after 2 failures it is not read for 600 seconds, and evidenceUnread
    says when it is read again. It
    shortlists the 3 stranded pairs (one experiment's subtracks named
    forward, plus or (+) and reverse, minus or (-)) that cover the most
    bases, ties to the most summed depth. For each gene it reads the depth
    over the gene on all 6 shortlisted subtracks and takes the one with the
    highest exon median; when every exon median is 0 the depth is not read
    and evidenceUnread says no shortlisted experiment has reads over the
    gene. With no stranded pair, the first unstranded subtrack of a track
    whose key or label holds unified, else the first unstranded subtrack, in
    label order. A bigWig read is at most 4 R-tree reads and 2 data blocks,
    the header and chromosome tree once per track and process; a sequence
    the bigWig does not list is not read, never read as zero depth. Beyond
    the junction reads and the reads made once per organism, the stages
    make at most 45 store reads per gene: one genome window, 2 peptide
    groups and 6 depth reads of at most 7 store reads each.
    A correction adds the gene's protein, the Orthologs table (one read
    whatever the group's size) and up to 16 ortholog proteins (each one
    gene record read of its transcripts and one transcript record read).
    geneIds pairs each id given with the site's own gene id it names (the
    same id, an alias or a previous id its gene record read resolves, a
    transcript id the site's text search names, or the one gene whose own id
    is the id with a ":" qualifier added); every other gene field holds that
    id. Each id given costs one gene record read; an id no record names adds
    one text search and one record read of the gene it names. Resolving ids
    uploads no gene list, and a refusal names an id that names several genes.

    Args:
        site_id: VEuPathDB site, for example 'plasmodb'.
        gene: The gene whose introns are checked.
    """
    reads: IntronReads | UncheckedIntrons = await read_inputs(
        site_id, intron_inputs(site_id, gene)
    )
    match reads:
        case UncheckedIntrons() as unchecked:
            return _unchecked(unchecked)
        case IntronReads():
            return await _judged(site_id, reads)

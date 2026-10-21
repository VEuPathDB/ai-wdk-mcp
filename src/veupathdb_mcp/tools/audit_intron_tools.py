"""The served intron support check, read from the site the call names."""

from __future__ import annotations

import httpx
from veupathdb.errors import VEuPathDBError

from veupathdb_mcp.audit.genes import GeneRow
from veupathdb_mcp.audit.introns import (
    CORRECTABLE,
    IntronAudit,
    IntronCorrection,
    IntronJudgement,
    UnreadIntron,
    correct_model,
    judge_introns,
)
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
    judgement = await run_in_a_slot(judge_introns, structure, reads.junctions)
    audit = {
        **judgement.model_dump(),
        "gene_ids": reads.gene_ids,
        "gene": reads.row.gene,
        "transcript": structure.transcript,
        "other_transcripts": structure.other_transcripts,
        "tracks_refused": reads.tracks_refused,
        "corrected_cds": None,
        "corrected_protein": None,
        "frame_kept": None,
        "code": None,
        "code_inferred": False,
        "orthologs": None,
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
    Every RNA-seq junction track the site serves for the gene's organism is
    read over the gene; junctions with no strand are set aside and counted
    (unstrandedIgnored). bestJunctionReads is what the expression gate
    measured: the reads of the best annotated intron, or, when no annotated
    intron has a read, of the best Strong Evidence junction on the gene's
    strand that lies wholly inside the gene; this second gate extends the
    prototype screen, which skipped such genes. The gene is NOT_EXPRESSED
    when that is under 50 reads, and then no intron is judged and unread is
    null. Each annotated
    intron of 20 bases or more with no read is listed in unread, with inCds
    and its own outcome: SHIFTED when one strong junction (Strong Evidence,
    20 reads or more) starts and ends within 30 bases of it, MISSING_EXON
    when a chain of two or more strong junctions spans it (an exon the model
    misses), UNEXPLAINED when none does. The verdict is
    UNSUPPORTED_UNEXPLAINED when any unread intron is unexplained, else
    UNSUPPORTED_MISSING_EXON when any is a missing exon, else
    UNSUPPORTED_SHIFTED; SUPPORTED means no unread intron. Only when every
    unread intron is explained are they all replaced together and the gene
    read from the genome: correctedCds (parts in ascending genome order, the
    stop codon included) and correctedProtein, with the genetic code the
    gene's own CDS and protein show (the standard code when codeInferred is
    false), and the ortholog count: among the first 60 genes of other
    species in the gene's ortholog table (named; read is how many served a
    protein), the closest copy in each of up to 8 species, and how many of
    them hold more 20-residue windows only the corrected protein has
    (forCorrected) or only the annotated one has (forAnnotated); reason says
    why there is no count. When the protein or the genome window for the
    correction cannot be read, the verdict and unread stay, the corrected
    fields, code and orthologs are null, and correctionReason says why.
    tracksRefused lists the tracks that do not index the gene's sequence,
    and is null when no track was read. NOT_CHECKED, with its reason, means
    the gene has no CDS or intron, the organism has no junction track, no
    track indexes the gene's sequence, or every junction over the gene has
    no strand; then introns and unread are null. A missing input of this
    kind is a NOT_CHECKED answer, not a tool error.
    geneIds pairs each id given with the site's own gene id it names (the
    same id, an alias, a transcript id, or the one gene whose own id is the
    id with a ":" qualifier added); every other gene field holds that id.

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

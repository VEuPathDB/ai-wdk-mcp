import pytest
from pydantic import ValidationError
from tests._support.intron_genes import (
    E1,
    E2,
    E3,
    E4,
    I1,
    I2,
    I3,
    SPLICED,
    dna,
    flipped,
    junction,
    structure,
)
from tests._support.proteins import PROTEIN
from veupathdb.errors import DataParsingError
from veupathdb.jbrowse import GenomeWindow

from veupathdb_mcp.audit.codes import GeneticCode
from veupathdb_mcp.audit.gene_ids import GeneId
from veupathdb_mcp.audit.intron_judge import (
    judge_introns,
)
from veupathdb_mcp.audit.introns import (
    GeneStructure,
    IntronAudit,
    IntronJudgement,
    IntronSupport,
    RnaJunction,
    UnreadIntron,
)
from veupathdb_mcp.audit.introns_correction import IntronCorrection, correct_model

STANDARD = GeneticCode.STANDARD
READS = [junction(I1, 100), junction(I2, 120), junction(I3, 300)]


def judged(judgement: IntronJudgement) -> list[UnreadIntron]:
    assert judgement.unread is not None
    return judgement.unread


def corrected(gene: GeneStructure, reads: list[RnaJunction]) -> IntronCorrection:
    return correct_model(gene, judged(judge_introns(gene, reads)), dna(), STANDARD)


def test_a_missing_exon_is_restored_in_frame() -> None:
    result = corrected(structure([E1, E3, E4]), READS)

    assert result == IntronCorrection(
        cds=[E1, E2, E3, E4], exons=[E1, E2, E3, E4], protein=SPLICED, frame_kept=True
    )


def test_every_explained_intron_is_replaced_together() -> None:
    gene = structure([E1, (1235, E2[1]), (1385, E3[1]), E4])
    reads = [junction(I1, 60), junction(I2, 900), junction(I3, 300)]

    result = corrected(gene, reads)

    assert (result.cds, result.protein) == ([E1, E2, E3, E4], SPLICED)
    assert len(result.protein) == 120


def test_a_missing_exon_and_a_shifted_intron_are_both_corrected() -> None:
    result = corrected(structure([E1, E3, (I3[1] + 25, E4[1])]), READS)

    assert (result.cds, result.protein) == ([E1, E2, E3, E4], SPLICED)


def test_a_correction_that_breaks_the_frame_says_so() -> None:
    reads = [junction((I1[0], I1[1] + 1), 900), junction(I2, 80), junction(I3, 300)]

    result = corrected(structure([E1, E2, E3, E4]), reads)

    assert result.frame_kept is False
    assert result.protein.startswith(PROTEIN[:30])
    assert result.protein != SPLICED


def test_a_minus_strand_gene_is_corrected_on_its_own_strand() -> None:
    gene, window, reads = flipped([E1, E3, E4], READS)
    judgement = judge_introns(gene, reads)

    result = correct_model(gene, judged(judgement), window, STANDARD)

    assert [(u.start, u.end) for u in judged(judgement)] == [(1304, 1513)]
    assert result.cds == [(1061, 1153), (1214, 1303), (1364, 1453), (1514, 1603)]
    assert result.protein == SPLICED


def test_a_stop_past_the_last_exon_extends_that_exon() -> None:
    gene = structure([E1, E3, (E4[0], E4[1] - 6)])

    result = corrected(gene, READS)

    assert result.cds == [E1, E2, E3, E4]
    assert result.exons == [E1, E2, E3, E4]
    assert result.protein == SPLICED


def test_a_minus_strand_stop_past_the_last_exon_extends_that_exon() -> None:
    gene, window, reads = flipped([E1, E3, (E4[0], E4[1] - 6)], READS)

    result = correct_model(gene, judged(judge_introns(gene, reads)), window, STANDARD)

    assert gene.exons[0] == (1067, 1153)
    assert result.cds == [(1061, 1153), (1214, 1303), (1364, 1453), (1514, 1603)]
    assert result.exons == result.cds
    assert result.protein == SPLICED


def test_a_correction_keeps_the_untranslated_exons() -> None:
    gene = structure([(1011, 1045), E1, E3, (E4[0], 1630)], cds=[E1, E3, E4])

    result = corrected(gene, READS)

    assert result.cds == [E1, E2, E3, E4]
    assert result.exons == [(1011, 1045), E1, E2, E3, (E4[0], 1630)]


def test_a_correction_whose_cds_leaves_its_exons_is_refused() -> None:
    with pytest.raises(ValidationError, match="lies inside its exons"):
        IntronCorrection(
            cds=[E1, E2], exons=[E1, (E2[0], E2[1] - 3)], protein="M", frame_kept=True
        )


def test_a_window_that_misses_the_gene_is_a_parsing_error() -> None:
    gene = structure([E1, E3, E4])
    short = GenomeWindow(seqid="contig", start=1100, sequence="ACGT" * 100)

    with pytest.raises(DataParsingError, match="PcyX_1-t1 lies outside the window"):
        correct_model(gene, judged(judge_introns(gene, READS)), short, STANDARD)


def test_a_judgement_verdict_follows_its_unread_introns() -> None:
    shifted = UnreadIntron(
        start=1151,
        end=1234,
        in_cds=True,
        outcome="SHIFTED",
        replacement=[IntronSupport(start=1151, end=1210, reads=900, tracks=1)],
    )

    with pytest.raises(ValidationError, match="names its unread introns"):
        IntronJudgement(
            verdict="UNSUPPORTED_MISSING_EXON",
            introns=[],
            unread=[shifted],
            best_junction_reads=900,
        )
    with pytest.raises(ValidationError, match="names its unread introns"):
        IntronJudgement(
            verdict="SUPPORTED", introns=[], unread=[shifted], best_junction_reads=900
        )


def test_an_unchecked_judgement_states_its_reason_and_no_count() -> None:
    with pytest.raises(ValidationError, match="names its unread introns"):
        IntronJudgement(
            verdict="NOT_CHECKED", introns=None, unread=None, best_junction_reads=0
        )
    with pytest.raises(ValidationError, match="names its unread introns"):
        IntronJudgement(
            verdict="NOT_EXPRESSED", introns=[], unread=[], best_junction_reads=10
        )

    assert IntronJudgement.not_checked("no track").best_junction_reads is None


def test_an_audit_corrects_only_a_shifted_or_missing_exon_verdict() -> None:
    with pytest.raises(ValidationError, match="every unread intron is explained"):
        IntronAudit(
            verdict="SUPPORTED",
            introns=[],
            unread=[],
            best_junction_reads=60,
            gene_ids=[GeneId(given="g1", resolved="g1")],
            gene="g1",
            transcript="g1-t1",
            other_transcripts=0,
            tracks_refused=[],
            evidence_unread=[],
            corrected_cds=None,
            corrected_protein=None,
            frame_kept=None,
            code=STANDARD,
            code_inferred=True,
            orthologs=None,
        )


def test_an_intron_audit_whose_gene_ids_name_another_gene_is_invalid() -> None:
    with pytest.raises(ValidationError, match="geneIds resolve to"):
        IntronAudit(
            verdict="SUPPORTED",
            introns=[],
            unread=[],
            best_junction_reads=60,
            gene_ids=[GeneId(given="g1", resolved="g2")],
            gene="g1",
            transcript="g1-t1",
            other_transcripts=0,
            tracks_refused=[],
            evidence_unread=[],
            corrected_cds=None,
            corrected_protein=None,
            frame_kept=None,
            code=None,
            code_inferred=False,
            orthologs=None,
        )

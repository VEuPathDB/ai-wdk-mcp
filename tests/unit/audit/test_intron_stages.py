import pytest
from tests._support.intron_genes import E1, E2, E3, E4, I1, I2, I3, junction, structure

from veupathdb_mcp.audit.intron_judge import (
    judge_introns,
    needs_depth,
    needs_motifs,
    needs_peptides,
)
from veupathdb_mcp.audit.introns import (
    IntronDepth,
    IntronEvidence,
    IntronJudgement,
    IntronSupport,
    PeptideSplit,
)

KEY = f"{I2[0]}-{I2[1]}"
MODEL = structure([E1, E2, E3, E4])
READ = [junction(I1, 400), junction(I3, 400)]


def depth(intron: float, exons: float = 400.0, covered: float = 1.0) -> IntronDepth:
    return IntronDepth(
        intron_median_depth=intron,
        exon_median_depth=exons,
        covered_share=covered,
        track="t",
    )


def judged(
    reads: list = READ, evidence: IntronEvidence | None = None
) -> IntronJudgement:
    return judge_introns(MODEL, reads, evidence or IntronEvidence())


def only_unread(judgement: IntronJudgement):
    assert judgement.unread is not None
    [unread] = judgement.unread
    return unread


def test_an_intron_whose_evidence_was_not_read_is_unexplained() -> None:
    unread = only_unread(judged())

    assert (unread.start, unread.end, unread.outcome) == (*I2, "UNEXPLAINED")
    assert (unread.motif, unread.depth, unread.replacement) == (None, None, [])


def test_each_stage_names_the_introns_it_reads_next() -> None:
    first = judged()
    canonical = judged(evidence=IntronEvidence(motifs={KEY: "GT..AG"}))
    measured = judged(
        evidence=IntronEvidence(motifs={KEY: "GT..AG"}, depth={KEY: depth(1.0)})
    )

    assert (needs_peptides(first), needs_motifs(first), needs_depth(first)) == (
        True,
        [I2],
        [I2],
    )
    assert (needs_motifs(canonical), needs_depth(canonical)) == ([], [I2])
    assert (needs_motifs(measured), needs_depth(measured)) == ([], [])


def test_a_gene_with_no_unread_intron_needs_no_stage() -> None:
    supported = judged([*READ, junction(I2, 30)])
    shifted = judged([*READ, junction((I2[0] + 30, I2[1] + 30), 200)])

    for judgement in (supported, shifted):
        assert (
            needs_peptides(judgement),
            needs_motifs(judgement),
            needs_depth(judgement),
        ) == (False, [], [])


def test_a_quarter_of_the_median_read_is_replaced_and_one_read_fewer_is_not() -> None:
    span = (I2[0] + 40, I2[1])

    replaced = only_unread(judged([*READ, junction(span, 100)]))
    short = only_unread(judged([*READ, junction(span, 99)]))

    assert replaced.outcome == "REPLACED"
    assert replaced.replacement == [
        IntronSupport(start=span[0], end=span[1], reads=100, tracks=1)
    ]
    assert (short.outcome, short.replacement) == ("UNEXPLAINED", [])


def test_a_junction_reaching_outside_the_gene_replaces_nothing() -> None:
    outside = (E1[0] - 500, E4[1] + 500)

    unread = only_unread(judged([*READ, junction(outside, 900)]))

    assert (unread.outcome, unread.replacement) == ("UNEXPLAINED", [])


def test_a_replacement_takes_the_most_read_overlapping_junction() -> None:
    weaker, stronger = (I2[0] + 40, I2[1]), (I2[0], I2[1] + 50)

    unread = only_unread(
        judged([*READ, junction(weaker, 150), junction(stronger, 180)])
    )

    assert unread.replacement == [
        IntronSupport(start=stronger[0], end=stronger[1], reads=180, tracks=1)
    ]


def test_a_junction_within_30_bases_at_both_ends_is_shifted_not_replaced() -> None:
    span = (I2[0] + 30, I2[1] + 30)

    unread = only_unread(judged([*READ, junction(span, 100)]))

    assert (unread.outcome, unread.replacement[0].start) == ("SHIFTED", span[0])


def test_a_gene_with_no_supported_intron_is_never_replaced() -> None:
    reads = [junction((I1[0] + 40, I1[1]), 500)]

    unread = judge_introns(structure([E1, E2]), reads, IntronEvidence()).unread

    assert unread is not None
    assert [u.outcome for u in unread] == ["UNEXPLAINED"]


@pytest.mark.parametrize(
    ("motif", "outcome"),
    [
        ("GT..AG", "UNEXPLAINED"),
        ("GC..AG", "UNEXPLAINED"),
        ("AT..AC", "NONCANONICAL"),
        ("GT..AC", "NONCANONICAL"),
    ],
)
def test_only_gt_ag_and_gc_ag_are_canonical(motif: str, outcome: str) -> None:
    unread = only_unread(judged(evidence=IntronEvidence(motifs={KEY: motif})))

    assert (unread.outcome, unread.motif) == (outcome, motif)


def test_a_noncanonical_intron_makes_the_gene_noncanonical() -> None:
    judgement = judged(evidence=IntronEvidence(motifs={KEY: "AT..AC"}))

    assert judgement.verdict == "UNSUPPORTED_NONCANONICAL"


def split(gap_start: int, gap_end: int) -> PeptideSplit:
    return PeptideSplit(
        before=(gap_start - 30, gap_start - 1), after=(gap_end + 1, gap_end + 30)
    )


@pytest.mark.parametrize("off", [0, 3, -3])
def test_a_peptide_split_across_the_intron_supports_it(off: int) -> None:
    peptides = (split(I2[0] + off, I2[1] - off),)

    judgement = judged(evidence=IntronEvidence(peptides=peptides))

    assert (judgement.verdict, judgement.unread) == ("SUPPORTED", [])


@pytest.mark.parametrize("gap", [(I2[0] + 4, I2[1]), (I2[0], I2[1] - 4)])
def test_a_peptide_gap_four_bases_off_does_not_clear(gap: tuple[int, int]) -> None:
    unread = only_unread(judged(evidence=IntronEvidence(peptides=(split(*gap),))))

    assert unread.outcome == "UNEXPLAINED"


def test_a_peptide_clears_only_an_intron_its_junctions_leave_unexplained() -> None:
    reads = [*READ, junction((I2[0] + 30, I2[1] + 30), 100)]

    judgement = judged(reads, IntronEvidence(peptides=(split(*I2),)))

    assert judgement.verdict == "UNSUPPORTED_SHIFTED"


def test_a_peptide_cleared_intron_does_not_block_another_from_being_retained() -> None:
    model = structure([E1, E2, E3, E4])
    reads = [junction(I1, 400)]
    i3 = f"{I3[0]}-{I3[1]}"
    evidence = IntronEvidence(
        peptides=(split(*I3),),
        motifs={KEY: "GT..AG"},
        depth={KEY: depth(400.0)},
    )

    judgement = judge_introns(model, reads, evidence)

    assert judgement.unread is not None
    assert [(u.start, u.outcome) for u in judgement.unread] == [(I2[0], "RETAINED")]
    assert i3 not in {f"{u.start}-{u.end}" for u in judgement.unread}


def test_an_intron_covered_at_a_quarter_of_its_exons_is_retained() -> None:
    evidence = IntronEvidence(motifs={KEY: "GT..AG"}, depth={KEY: depth(100.0)})

    judgement = judged(evidence=evidence)
    unread = only_unread(judgement)

    assert (judgement.verdict, unread.outcome) == ("UNSUPPORTED_RETAINED", "RETAINED")
    assert unread.depth == depth(100.0)
    assert unread.depth is not None
    assert unread.depth.depth_share == 0.25


def test_one_below_the_depth_threshold_is_not_retained() -> None:
    unread = only_unread(judged(evidence=IntronEvidence(depth={KEY: depth(99.0)})))

    assert (unread.outcome, unread.depth) == ("UNEXPLAINED", depth(99.0))


@pytest.mark.parametrize(
    ("covered", "outcome"), [(0.9, "RETAINED"), (0.899, "UNEXPLAINED")]
)
def test_an_intron_is_retained_only_when_nine_tenths_of_it_is_covered(
    covered: float, outcome: str
) -> None:
    evidence = IntronEvidence(depth={KEY: depth(100.0, covered=covered)})

    assert only_unread(judged(evidence=evidence)).outcome == outcome


def test_an_intron_is_retained_only_when_every_other_intron_is_strongly_read() -> None:
    reads = [junction(I1, 400), junction(I3, 19)]

    unread = only_unread(judged(reads, IntronEvidence(depth={KEY: depth(400.0)})))

    assert unread.outcome == "UNEXPLAINED"


def test_an_exon_median_of_zero_never_retains() -> None:
    unread = only_unread(
        judged(evidence=IntronEvidence(depth={KEY: depth(0.0, exons=0.0)}))
    )

    assert unread.outcome == "UNEXPLAINED"
    assert unread.depth is not None
    assert unread.depth.depth_share == 0.0


def test_a_noncanonical_motif_outranks_a_retained_depth() -> None:
    evidence = IntronEvidence(motifs={KEY: "AT..AC"}, depth={KEY: depth(400.0)})

    assert only_unread(judged(evidence=evidence)).outcome == "NONCANONICAL"


def test_the_verdict_ranks_unexplained_first_and_shifted_last() -> None:
    reads = [junction(I1, 400), junction((I3[0] + 30, I3[1] + 30), 400)]
    model = structure([E1, E2, E3, E4])
    evidence = IntronEvidence(
        motifs={KEY: "GT..AG", f"{I1[0]}-{I1[1]}": "GT..AG"},
        depth={KEY: depth(1.0)},
    )

    judgement = judge_introns(model, reads, evidence)

    assert judgement.unread is not None
    assert [u.outcome for u in judgement.unread] == ["UNEXPLAINED", "SHIFTED"]
    assert judgement.verdict == "UNSUPPORTED_UNEXPLAINED"

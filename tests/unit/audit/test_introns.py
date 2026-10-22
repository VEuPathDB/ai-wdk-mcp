import pytest
from tests._support.intron_genes import (
    E1,
    E2,
    E3,
    E4,
    I1,
    I2,
    I3,
    junction,
    structure,
)

from veupathdb_mcp.audit.intron_judge import (
    judge_introns,
)
from veupathdb_mcp.audit.introns import (
    IntronSupport,
    UnreadIntron,
)

WHOLE = (I1[0], I2[1])
SHIFTED = (I1[0], I1[1] + 24)
SHORT_E2 = (SHIFTED[1] + 1, E2[1])


def unread(
    span: tuple[int, int], outcome: str, *replacement: IntronSupport
) -> UnreadIntron:
    return UnreadIntron.model_validate(
        {
            "start": span[0],
            "end": span[1],
            "in_cds": True,
            "outcome": outcome,
            "replacement": list(replacement),
        }
    )


def read(span: tuple[int, int], reads: int, tracks: int = 1) -> IntronSupport:
    return IntronSupport(start=span[0], end=span[1], reads=reads, tracks=tracks)


def test_an_unread_intron_that_hides_an_exon_is_a_missing_exon() -> None:
    reads = [junction(I1, 100), junction(I2, 120), junction(I3, 300)]

    result = judge_introns(structure([E1, E3, E4]), reads)

    assert result.verdict == "UNSUPPORTED_MISSING_EXON"
    assert result.introns == [read(WHOLE, 0, 0), read(I3, 300)]
    assert result.unread == [
        unread(WHOLE, "MISSING_EXON", read(I1, 100), read(I2, 120))
    ]
    assert (result.best_junction_reads, result.reason) == (300, None)


def test_an_unread_intron_beside_a_read_one_24_bases_shorter_is_shifted() -> None:
    reads = [junction(I1, 900), junction(I2, 80), junction(I3, 300)]

    result = judge_introns(structure([E1, SHORT_E2, E3, E4]), reads)

    assert result.verdict == "UNSUPPORTED_SHIFTED"
    assert result.unread == [unread(SHIFTED, "SHIFTED", read(I1, 900))]


def test_a_gene_whose_every_intron_is_read_is_supported() -> None:
    reads = [junction(I1, 60), junction(I2, 3), junction(I3, 1)]

    result = judge_introns(structure([E1, E2, E3, E4]), reads)

    assert result.verdict == "SUPPORTED"
    assert result.introns is not None
    assert [i.reads for i in result.introns] == [60, 3, 1]
    assert (result.unread, result.best_junction_reads) == ([], 60)


def test_a_gene_with_no_reads_anywhere_is_not_expressed_with_none_measured() -> None:
    result = judge_introns(structure([E1, E3, E4]), [])

    assert result.verdict == "NOT_EXPRESSED"
    assert result.introns is not None
    assert ([i.reads for i in result.introns], result.best_junction_reads) == (
        [0, 0],
        0,
    )
    assert result.unread is None


@pytest.mark.parametrize(
    ("best", "verdict"),
    [(49, "NOT_EXPRESSED"), (50, "UNSUPPORTED_MISSING_EXON")],
)
def test_a_gene_with_a_read_intron_is_gated_on_its_best_annotated_intron(
    best: int, verdict: str
) -> None:
    reads = [junction(I1, 1000), junction(I2, 1200), junction(I3, best)]

    result = judge_introns(structure([E1, E3, E4]), reads)

    assert (result.verdict, result.best_junction_reads) == (verdict, best)


@pytest.mark.parametrize("strong", [True, False])
def test_a_novel_junction_never_opens_the_gate_of_a_gene_with_a_read_intron(
    strong: bool,
) -> None:
    reads = [junction(I2, 30), junction((1240, 1280), 1000, strong=strong)]

    result = judge_introns(structure([E1, SHORT_E2, E3]), reads)

    assert (result.verdict, result.best_junction_reads) == ("NOT_EXPRESSED", 30)


def test_a_gene_whose_only_intron_is_unread_is_judged_by_its_junctions() -> None:
    result = judge_introns(structure([E1, SHORT_E2]), [junction(I1, 1000)])

    assert result.verdict == "UNSUPPORTED_SHIFTED"
    assert result.introns == [read(SHIFTED, 0, 0)]
    assert result.unread == [unread(SHIFTED, "SHIFTED", read(I1, 1000))]
    assert result.best_junction_reads == 1000


@pytest.mark.parametrize(
    ("best", "verdict"), [(49, "NOT_EXPRESSED"), (50, "UNSUPPORTED_SHIFTED")]
)
def test_a_gene_with_no_read_intron_is_expressed_from_a_50_read_strong_junction(
    best: int, verdict: str
) -> None:
    result = judge_introns(structure([E1, SHORT_E2]), [junction(I1, best)])

    assert (result.verdict, result.best_junction_reads) == (verdict, best)


@pytest.mark.parametrize("span", [I1, (1240, 1280)])
def test_a_weak_junction_does_not_show_an_unread_gene_is_expressed(
    span: tuple[int, int],
) -> None:
    reads = [junction(span, 1000, strong=False)]

    result = judge_introns(structure([E1, SHORT_E2]), reads)

    assert (result.verdict, result.best_junction_reads) == ("NOT_EXPRESSED", 0)


def test_a_junction_reaching_outside_the_gene_shows_no_expression() -> None:
    gene = structure([E1, SHORT_E2])

    result = judge_introns(gene, [junction((1001, 1100), 1000)])

    assert (result.verdict, result.best_junction_reads) == ("NOT_EXPRESSED", 0)


def test_an_unread_intron_with_no_strong_junction_near_it_is_unexplained() -> None:
    reads = [
        junction(I1, 100, strong=False),
        junction(I2, 120, strong=False),
        junction(I3, 300),
    ]

    result = judge_introns(structure([E1, E3, E4]), reads)

    assert result.verdict == "UNSUPPORTED_UNEXPLAINED"
    assert result.unread == [unread(WHOLE, "UNEXPLAINED")]


def test_a_strong_junction_under_20_reads_links_no_chain() -> None:
    reads = [junction(I1, 19), junction(I2, 120), junction(I3, 300)]

    result = judge_introns(structure([E1, E3, E4]), reads)

    assert result.verdict == "UNSUPPORTED_REPLACED"
    assert result.unread == [unread(WHOLE, "REPLACED", read(I2, 120))]


def test_a_junction_on_the_other_strand_neither_reads_nor_explains() -> None:
    reads = [
        junction(I1, 100, strand="-"),
        junction(I2, 120, strand="-"),
        junction(I3, 300),
        junction(WHOLE, 500, strand="-"),
    ]

    result = judge_introns(structure([E1, E3, E4]), reads)

    assert result.verdict == "UNSUPPORTED_UNEXPLAINED"
    assert result.introns is not None
    assert (result.introns[0].reads, result.best_junction_reads) == (0, 300)


def test_an_unstranded_junction_is_set_aside_and_counted() -> None:
    reads = [
        junction(I1, 100),
        junction(I2, 120),
        junction(I3, 300),
        junction((1240, 1280), 2, strand="."),
        junction(WHOLE, 900, strand="?"),
    ]

    result = judge_introns(structure([E1, E3, E4]), reads)

    assert result.verdict == "UNSUPPORTED_MISSING_EXON"
    assert result.introns is not None
    assert (result.unstranded_ignored, result.introns[0].reads) == (2, 0)


def test_a_gene_whose_every_junction_is_unstranded_is_unchecked() -> None:
    reads = [junction(I1, 100, strand="."), junction(I3, 300, strand=".")]

    result = judge_introns(structure([E1, E3, E4]), reads)

    assert result.verdict == "NOT_CHECKED"
    assert result.reason == "every junction over PcyX_1-t1 is unstranded (2 junctions)"
    assert (result.introns, result.unread, result.best_junction_reads) == (
        None,
        None,
        None,
    )
    assert result.unstranded_ignored == 2


def test_a_replacement_30_bases_off_is_shifted_and_31_is_replaced() -> None:
    gene = structure([E1, (I1[1] + 31, E2[1]), E3, E4])
    near = [junction(I1, 900), junction(I2, 80), junction(I3, 300)]
    far = [junction((I1[0] + 31, I1[1]), 900), junction(I2, 80), junction(I3, 300)]

    assert judge_introns(gene, near).verdict == "UNSUPPORTED_SHIFTED"
    assert judge_introns(gene, far).verdict == "UNSUPPORTED_REPLACED"


def test_an_intron_under_20_bases_is_never_flagged() -> None:
    gene = structure([E1, (E1[1] + 20, E2[1]), E3, E4])
    reads = [junction(I2, 120), junction(I3, 300)]

    result = judge_introns(gene, reads)

    assert result.verdict == "SUPPORTED"
    assert result.introns is not None
    assert result.introns[0] == read((1151, 1169), 0, 0)


def test_an_intron_read_on_two_tracks_counts_its_best_track() -> None:
    reads = [
        junction(I1, 100),
        junction(I1, 140, track="second"),
        junction(I2, 3),
        junction(I3, 300),
    ]

    result = judge_introns(structure([E1, E2, E3, E4]), reads)

    assert result.introns is not None
    assert result.introns[0] == read(I1, 140, 2)


def test_the_best_read_chain_replaces_the_unread_intron() -> None:
    reads = [
        junction(I1, 100),
        junction(I2, 120),
        junction((I1[0], I2[1] - 10), 40),
        junction(I3, 300),
    ]

    result = judge_introns(structure([E1, E3, E4]), reads)

    assert result.unread is not None
    assert result.unread[0].replacement == [read(I1, 100), read(I2, 120)]


def test_a_chain_is_kept_only_when_its_weakest_link_beats_the_best_so_far() -> None:
    reads = [
        junction(I1, 30),
        junction(I2, 120),
        junction((I1[0], I2[1] - 10), 40),
        junction(I3, 300),
    ]

    result = judge_introns(structure([E1, E3, E4]), reads)

    assert result.unread == [unread(WHOLE, "SHIFTED", read((1151, 1350), 40))]


@pytest.mark.parametrize(
    ("step", "verdict"),
    [(1999, "UNSUPPORTED_MISSING_EXON"), (2000, "UNSUPPORTED_REPLACED")],
)
def test_a_chain_links_junctions_under_2000_bases_apart(
    step: int, verdict: str
) -> None:
    gene = structure([E1, (3400, 3489), (3600, 3689)])
    reads = [
        junction(I1, 100),
        junction((I1[1] + step, 3399), 100),
        junction((3490, 3599), 300),
    ]

    assert judge_introns(gene, reads).verdict == verdict


def test_every_unread_intron_is_judged_on_its_own() -> None:
    gene = structure([E1, SHORT_E2, (I2[1] + 25, E3[1]), E4])
    reads = [junction(I1, 60), junction(I2, 900), junction(I3, 300)]

    result = judge_introns(gene, reads)

    assert result.verdict == "UNSUPPORTED_SHIFTED"
    assert result.unread == [
        unread(SHIFTED, "SHIFTED", read(I1, 60)),
        unread((1301, 1384), "SHIFTED", read(I2, 900)),
    ]
    assert result.introns is not None
    assert [i.reads for i in result.introns] == [0, 0, 300]


def test_one_unexplained_intron_makes_the_gene_unexplained() -> None:
    gene = structure([E1, SHORT_E2, (I2[1] + 25, E3[1]), E4])
    reads = [junction(I1, 60), junction(I2, 900, strong=False), junction(I3, 300)]

    result = judge_introns(gene, reads)

    assert result.verdict == "UNSUPPORTED_UNEXPLAINED"
    assert result.unread is not None
    assert [u.outcome for u in result.unread] == ["SHIFTED", "UNEXPLAINED"]


def test_a_missing_exon_beside_a_shifted_intron_makes_a_missing_exon_gene() -> None:
    gene = structure([E1, E3, (I3[1] + 25, E4[1])])
    reads = [junction(I1, 100), junction(I2, 120), junction(I3, 300)]

    result = judge_introns(gene, reads)

    assert result.verdict == "UNSUPPORTED_MISSING_EXON"
    assert result.unread is not None
    assert [u.outcome for u in result.unread] == ["MISSING_EXON", "SHIFTED"]


def test_an_unread_intron_outside_the_cds_says_so() -> None:
    gene = structure([(1001, 1030), E1, E2, E3, E4], cds=[E1, E2, E3, E4])
    reads = [junction(I1, 100), junction(I2, 100), junction(I3, 100)]

    result = judge_introns(gene, reads)

    assert result.verdict == "UNSUPPORTED_UNEXPLAINED"
    assert result.unread is not None
    assert [(u.start, u.end, u.in_cds) for u in result.unread] == [(1031, 1060, False)]


def test_a_not_expressed_gene_counts_the_unstranded_junctions_set_aside() -> None:
    reads = [junction(I3, 10), junction(I1, 900, strand=".")]

    result = judge_introns(structure([E1, E3, E4]), reads)

    assert (result.verdict, result.best_junction_reads) == ("NOT_EXPRESSED", 10)
    assert result.unstranded_ignored == 1

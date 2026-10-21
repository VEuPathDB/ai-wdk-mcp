import pytest
from pydantic import ValidationError
from tests._support.proteins import PROTEIN, row
from veupathdb.errors import DataParsingError

from veupathdb_mcp.audit.fusion import FusionCheck, beside, check_fusion, copies_beside
from veupathdb_mcp.audit.genes import GeneRow

REFERENCE = PROTEIN[:120]
NEIGHBOUR = PROTEIN[120:]
UNRELATED = (
    "RVRRTWHGTSYGERLFDVCYPRYGYATDCCHIYARMRWHTILSADRKQVDKMITLADWEPELPDAAHHCSPPQDWHKMDL"
)
OTHER = "Toxoplasma gondii ME49"


def named(check: FusionCheck) -> tuple[str | None, str | None, int]:
    return (check.partner, check.closest_neighbour, check.neighbour_windows)


def test_a_member_that_holds_a_neighbour_after_the_reference_matches_it() -> None:
    check = check_fusion(
        REFERENCE + NEIGHBOUR, REFERENCE, {"N1": NEIGHBOUR, "N2": UNRELATED}
    )

    assert check.verdict == "EXTRA_MATCHES_NEIGHBOUR"
    assert (check.extra, check.extra_windows) == ([(111, 200)], 8)
    assert named(check) == ("N1", None, 7)


def test_a_member_whose_extra_residues_no_neighbour_holds_is_unexplained() -> None:
    check = check_fusion(REFERENCE + UNRELATED, REFERENCE, {"N1": NEIGHBOUR})

    assert check.verdict == "EXTRA_UNEXPLAINED"
    assert (check.extra, check.extra_windows) == ([(111, 200)], 8)
    assert named(check) == (None, None, 0)


def test_a_member_equal_to_its_reference_holds_no_extra_residues() -> None:
    check = check_fusion(REFERENCE, REFERENCE, {"N1": NEIGHBOUR})

    assert check.verdict == "NO_EXTRA"
    assert (check.extra, check.extra_windows) == ([], 0)
    assert named(check) == (None, None, 0)


@pytest.mark.parametrize(
    "member",
    [
        REFERENCE + REFERENCE,
        REFERENCE[:60] + "KE" * 50 + REFERENCE[60:],
        REFERENCE[:60] + "ASASGSGSAS" * 10 + REFERENCE[60:],
    ],
)
def test_a_tandem_duplicate_or_a_repeat_expansion_holds_no_extra_window(
    member: str,
) -> None:
    check = check_fusion(member, REFERENCE, {"N1": NEIGHBOUR})

    assert (check.verdict, check.extra, named(check)) == (
        "NO_EXTRA",
        [],
        (None, None, 0),
    )


def test_a_neighbour_that_holds_too_few_windows_is_the_closest_not_a_partner() -> None:
    member = REFERENCE + UNRELATED[:60] + NEIGHBOUR[:30]

    check = check_fusion(member, REFERENCE, {"N1": NEIGHBOUR})

    assert check.verdict == "EXTRA_UNEXPLAINED"
    assert check.extra_windows == 9
    assert named(check) == (None, "N1", 2)


def test_a_window_held_at_half_identity_counts_for_the_neighbour() -> None:
    half = "".join(c if i % 2 == 0 else "X" for i, c in enumerate(NEIGHBOUR))

    check = check_fusion(REFERENCE + NEIGHBOUR, REFERENCE, {"N1": half})

    assert (check.verdict, *named(check)) == ("EXTRA_MATCHES_NEIGHBOUR", "N1", None, 7)


def test_a_neighbour_without_a_protein_holds_no_window() -> None:
    check = check_fusion(REFERENCE + NEIGHBOUR, REFERENCE, {"N1": ""})

    assert (check.verdict, *named(check)) == ("EXTRA_UNEXPLAINED", None, None, 0)


@pytest.mark.parametrize(
    ("extra", "windows", "verdict"),
    [
        ([(111, 200)], 4, "EXTRA_MATCHES_NEIGHBOUR"),
        ([(111, 200)], 3, "EXTRA_UNEXPLAINED"),
        ([(1, 40)], 3, "EXTRA_MATCHES_NEIGHBOUR"),
        ([(1, 40)], 2, "EXTRA_UNEXPLAINED"),
    ],
)
def test_a_match_needs_three_windows_and_two_fifths_of_the_extra_ones(
    extra: list[tuple[int, int]], windows: int, verdict: str
) -> None:
    matched = verdict == "EXTRA_MATCHES_NEIGHBOUR"
    check = FusionCheck(
        extra=extra,
        partner="N1" if matched else None,
        closest_neighbour=None if matched else "N1",
        neighbour_windows=windows,
    )

    assert check.verdict == verdict


def test_a_check_counts_windows_over_every_extra_run() -> None:
    check = FusionCheck(
        extra=[(1, 40), (111, 200)],
        partner=None,
        closest_neighbour=None,
        neighbour_windows=0,
    )

    assert check.extra_windows == 11


@pytest.mark.parametrize(
    ("partner", "closest", "windows", "message"),
    [
        ("N1", None, 0, "names a neighbour when and only when"),
        (None, None, 2, "names a neighbour when and only when"),
        ("N1", "N2", 4, "names a partner or a closest neighbour, not both"),
        ("N1", None, 9, "holds at most the 8 extra windows"),
        (
            "N1",
            None,
            3,
            "names a partner when and only when the extra residues match a neighbour",
        ),
        (
            None,
            "N1",
            4,
            "names a partner when and only when the extra residues match a neighbour",
        ),
    ],
)
def test_a_check_with_an_impossible_neighbour_is_refused(
    partner: str | None, closest: str | None, windows: int, message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        FusionCheck(
            extra=[(111, 200)],
            partner=partner,
            closest_neighbour=closest,
            neighbour_windows=windows,
        )


def test_a_run_that_ends_before_its_start_is_refused() -> None:
    with pytest.raises(ValidationError, match="ends at 40, before its start 60"):
        FusionCheck(
            extra=[(60, 40)],
            partner=None,
            closest_neighbour=None,
            neighbour_windows=0,
        )


def _contig(genes: int, seqid: str = "chrI") -> list[GeneRow]:
    return [
        row(f"G{i}", OTHER, 300, start=1000 * i + 1).model_copy(
            update={"sequence_id": seqid}
        )
        for i in range(genes)
    ]


def test_the_genes_beside_a_gene_are_three_on_each_side_of_its_contig() -> None:
    genome = [*reversed(_contig(10)), *_contig(3, "chrII")]

    assert [r.gene for r in beside(genome[5], genome)] == [
        "G1",
        "G2",
        "G3",
        "G5",
        "G6",
        "G7",
    ]


def test_a_gene_near_a_contig_end_has_fewer_genes_on_that_side() -> None:
    genome = _contig(10)

    assert [r.gene for r in beside(genome[1], genome)] == ["G0", "G2", "G3", "G4"]


def test_genes_that_start_together_are_ordered_by_name() -> None:
    genome = [
        row(name, OTHER, 300, start=5001).model_copy(update={"sequence_id": "chrI"})
        for name in ("C", "A", "B")
    ]

    assert [r.gene for r in beside(genome[2], genome)] == ["A", "C"]


def test_a_genome_without_the_gene_is_refused() -> None:
    gene = row("MISSING", OTHER, 300)

    with pytest.raises(DataParsingError, match="holds no MISSING on MISSING_contig"):
        beside(gene, _contig(3))


def test_the_copies_beside_a_gene_are_its_neighbours_in_the_partner_group() -> None:
    genome = _contig(9)
    genome[2] = genome[2].model_copy(update={"ortholog_group": "OG7_0000777"})
    genome[8] = genome[8].model_copy(update={"ortholog_group": "OG7_0000777"})

    assert copies_beside(genome[4], genome, "OG7_0000777") == ["G2"]

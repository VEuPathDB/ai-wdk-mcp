import pytest
from tests._support.proteins import PROTEIN

from veupathdb_mcp.audit.length import LengthVerdict
from veupathdb_mcp.audit.strain import judged_side, missing_runs, tie_break

SEGMENT = "ACDEFGHIKLMNPQRSTVWY" * 2


def test_a_forty_residue_internal_deletion_is_one_run() -> None:
    assert missing_runs(PROTEIN, PROTEIN[:80] + PROTEIN[120:]) == [(81, 120)]


def test_a_deleted_segment_lacks_nothing_the_other_way() -> None:
    assert missing_runs(PROTEIN[:80] + PROTEIN[120:], PROTEIN) == []


def test_an_inserted_segment_is_a_run_of_the_longer_protein() -> None:
    assert missing_runs(PROTEIN[:100] + SEGMENT + PROTEIN[100:], PROTEIN) == [
        (101, 140)
    ]


def test_a_poly_n_stretch_is_low_complexity_and_ignored() -> None:
    assert missing_runs(PROTEIN[:80] + "N" * 40 + PROTEIN[80:], PROTEIN) == []


@pytest.mark.parametrize(
    "stretch",
    [
        "RRDKSRRKRKSESEKEDSKSTSEKDTDTKRSDKRKSTESR",
        "QQQKQSQLQNQHQFQFQYQVQFQEQMQVQNQMQHQSQTQC",
    ],
)
def test_a_stretch_of_few_letters_or_one_frequent_letter_is_ignored(
    stretch: str,
) -> None:
    assert missing_runs(PROTEIN[:80] + stretch + PROTEIN[80:], PROTEIN) == []


def test_a_window_repeated_elsewhere_in_the_source_is_ignored() -> None:
    source = PROTEIN[:100] + SEGMENT + PROTEIN[100:] + SEGMENT

    assert missing_runs(source, PROTEIN) == []


def test_a_single_missing_window_is_not_a_run() -> None:
    assert missing_runs(PROTEIN, PROTEIN[:90] + PROTEIN[100:]) == []


def test_a_protein_shorter_than_a_window_has_no_runs() -> None:
    assert missing_runs(PROTEIN[:19], "") == []


def test_a_window_over_the_end_of_the_target_is_part_of_a_missing_tail() -> None:
    assert missing_runs(PROTEIN, PROTEIN[:140]) == [(131, 200)]


@pytest.mark.parametrize(
    ("reference", "strain", "relatives", "side"),
    [
        (319, 110, 300.0, "STRAIN_SHORT"),
        (617, 466, 470.0, "REFERENCE_LONG"),
        (500, 450, None, "NO_RELATIVES"),
        (330, 269, 300.0, "STRAIN_SHORT"),
        (330, 270, 300.0, "UNCLEAR"),
        (331, 300, 300.0, "REFERENCE_LONG"),
        (314, 289, 312.0, "UNCLEAR"),
        (341, 280, 4008.0, "UNCLEAR"),
        (300, 400, 300.0, "UNCLEAR"),
        (200, 300, 300.0, "UNCLEAR"),
    ],
)
def test_the_relatives_decide_which_side_is_wrong(
    reference: int, strain: int, relatives: float | None, side: str
) -> None:
    assert tie_break(reference, strain, relatives) == side


@pytest.mark.parametrize("verdict", ["NOT_CHECKED", "ABSENT", "ASSEMBLY", "NOT_SHORT"])
def test_a_side_is_judged_only_where_the_strain_genome_encodes_the_lost_run(
    verdict: LengthVerdict,
) -> None:
    assert judged_side(verdict, 319, 110, 300.0) == "NOT_JUDGED"
    assert judged_side(verdict, 500, 450, None) == "NOT_JUDGED"


@pytest.mark.parametrize(
    ("reference", "strain", "relatives", "side"),
    [
        (319, 110, 300.0, "STRAIN_SHORT"),
        (617, 466, 470.0, "REFERENCE_LONG"),
        (314, 289, 309.0, "UNCLEAR"),
        (500, 450, None, "NO_RELATIVES"),
    ],
)
def test_a_genome_that_encodes_the_lost_run_lets_the_relatives_decide(
    reference: int, strain: int, relatives: float | None, side: str
) -> None:
    assert judged_side("GENOME_ENCODES", reference, strain, relatives) == side

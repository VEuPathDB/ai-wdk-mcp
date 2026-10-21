import pytest
from tests._support.proteins import PROTEIN, back_translate

from veupathdb_mcp.audit.codes import GeneticCode, reverse_complement
from veupathdb_mcp.audit.organelle import (
    ORGANELLE_MATCHED,
    ORGANELLE_MIN_OVERLAP,
    ORGANELLE_OVERLAP_AGREEMENT,
    ORGANELLE_SHORT_PERIOD,
    ORGANELLE_WORD,
    EndOverlap,
    check_circular_join,
    end_overlap,
)

SPACER = "C" * 2000
CUT = 301


def on_the_line(coding: str) -> str:
    return "G" * 300 + coding + SPACER + SPACER


def gene(protein: str = PROTEIN) -> str:
    return back_translate(protein) + "TAA"


def tga_for_w(protein: str) -> str:
    return "".join("TGA" if a == "W" else back_translate(a) for a in protein) + "TAA"


def split(coding: str, overlap: int = 0) -> str:
    return coding[CUT:] + SPACER + coding[: CUT + overlap]


def changed(dna: str, positions: list[int]) -> str:
    bases = list(dna)
    for at in positions:
        bases[at] = "T" if bases[at] != "T" else "A"
    return "".join(bases)


def mutated(changes: int) -> str:
    step = len(PROTEIN) // (changes + 1)
    residues = list(PROTEIN)
    for k in range(1, changes + 1):
        residues[k * step] = "G" if residues[k * step] != "G" else "A"
    return "".join(residues)


def test_a_gene_cut_by_the_contig_ends_is_split_at_the_join() -> None:
    result = check_circular_join(split(gene()), PROTEIN, GeneticCode.STANDARD)

    assert result.verdict == "SPLIT_AT_JOIN"
    assert (result.best_linear, result.best_circular) == (100, 200)
    assert (result.reference_length, result.overlap_bases) == (200, 0)


def test_a_minus_strand_gene_cut_by_the_contig_ends_is_split_at_the_join() -> None:
    contig_dna = reverse_complement(split(gene()))

    result = check_circular_join(contig_dna, PROTEIN, GeneticCode.STANDARD)

    assert result.verdict == "SPLIT_AT_JOIN"
    assert (result.best_linear, result.best_circular) == (100, 200)


@pytest.mark.parametrize("overlap", [20, 87, 126, 127])
def test_ends_that_repeat_each_other_are_joined_once(overlap: int) -> None:
    result = check_circular_join(split(gene(), overlap), PROTEIN, GeneticCode.STANDARD)

    assert result.verdict == "SPLIT_AT_JOIN"
    assert (result.overlap_bases, result.overlap_mismatches) == (overlap, 0)
    assert result.best_circular == 200


def test_an_overlap_with_one_differing_base_in_127_is_joined() -> None:
    stored = changed(split(gene(), 127), [-1])

    result = check_circular_join(stored, PROTEIN, GeneticCode.STANDARD)

    assert ORGANELLE_OVERLAP_AGREEMENT == 0.99
    assert end_overlap(stored) == EndOverlap(bases=127, mismatches=1)
    assert result.verdict == "SPLIT_AT_JOIN"
    assert (result.overlap_bases, result.overlap_mismatches) == (127, 1)
    assert (result.best_linear, result.best_circular) == (142, 200)


def test_a_twenty_base_end_match_with_two_differing_bases_is_no_overlap() -> None:
    stored = changed(split(gene(), 20), [-1, -10])

    assert end_overlap(stored) == EndOverlap(bases=0, mismatches=0)


def test_a_repeat_under_twenty_bases_is_not_an_overlap() -> None:
    assert ORGANELLE_MIN_OVERLAP == 20
    assert end_overlap(split(gene(), 19)).bases == 0
    assert end_overlap(split(gene(), 20)) == EndOverlap(bases=20, mismatches=0)


def test_an_overlap_is_at_most_half_the_contig() -> None:
    assert end_overlap("ACGTAAC" * 30).bases == 105
    assert end_overlap("").bases == 0


@pytest.mark.parametrize(
    ("start", "end"),
    [
        ("A" * 30, "A" * 30),
        ("AT" * 12, "AT" * 12),
        ("TA" * 12, "AT" * 12),
        ("TATTTA" * 5, "TATTTA" * 5),
    ],
)
def test_ends_in_one_short_period_run_are_no_overlap(start: str, end: str) -> None:
    assert ORGANELLE_SHORT_PERIOD == 6
    assert end_overlap(start + gene() + SPACER + end) == EndOverlap(
        bases=0, mismatches=0
    )


def test_ends_in_a_seven_base_period_run_are_an_overlap() -> None:
    run = "TATTTAA" * 5

    assert end_overlap(run + gene() + SPACER + run) == EndOverlap(
        bases=35, mismatches=0
    )


def test_a_contig_that_holds_the_whole_gene_is_intact_on_the_line() -> None:
    result = check_circular_join(on_the_line(gene()), PROTEIN, GeneticCode.STANDARD)

    assert result.verdict == "INTACT_ON_THE_LINE"
    assert (result.best_linear, result.best_circular) == (200, 200)
    assert result.overlap_bases == 0


def test_a_whole_minus_strand_gene_is_intact_on_the_line() -> None:
    contig_dna = reverse_complement(on_the_line(gene()))

    result = check_circular_join(contig_dna, PROTEIN, GeneticCode.STANDARD)

    assert result.verdict == "INTACT_ON_THE_LINE"
    assert (result.best_linear, result.best_circular) == (200, 200)


def test_a_gene_across_the_middle_of_the_contig_is_intact_on_the_line() -> None:
    contig_dna = "G" * 2000 + gene() + SPACER

    result = check_circular_join(contig_dna, PROTEIN, GeneticCode.STANDARD)

    assert result.verdict == "INTACT_ON_THE_LINE"
    assert (result.best_linear, result.best_circular) == (200, 100)


def test_a_reference_longer_than_half_the_circle_is_refused() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "the reference codes 200 residues, 600 bases, more than half of "
            "the 300-base circle; a turn by half cannot place it whole"
        ),
    ):
        check_circular_join(gene()[:300], PROTEIN, GeneticCode.STANDARD)


def test_the_half_refusal_reads_the_circle_not_the_stored_contig() -> None:
    coding = gene()
    stored = coding[CUT:] + "C" * 500 + coding[: CUT + 127]

    assert (len(stored), end_overlap(stored).bases) == (1230, 127)
    with pytest.raises(ValueError, match="half of the 1103-base circle"):
        check_circular_join(stored, PROTEIN, GeneticCode.STANDARD)


def test_a_contig_without_the_gene_is_not_found() -> None:
    contig_dna = on_the_line(gene(PROTEIN[:150]))

    result = check_circular_join(contig_dna, PROTEIN, GeneticCode.STANDARD)

    assert result.verdict == "NOT_FOUND"
    assert (result.best_linear, result.best_circular) == (150, 150)


def test_a_tga_tryptophan_gene_is_found_only_under_its_own_code() -> None:
    contig_dna = split(tga_for_w(PROTEIN))

    found = check_circular_join(contig_dna, PROTEIN, GeneticCode.UGA_TRYPTOPHAN)
    stopped = check_circular_join(contig_dna, PROTEIN, GeneticCode.STANDARD)

    assert found.verdict == "SPLIT_AT_JOIN"
    assert found.best_circular == 200
    assert stopped.verdict == "NOT_FOUND"
    assert stopped.best_circular == max(len(run) for run in PROTEIN.split("W"))


@pytest.mark.parametrize(
    ("changes", "verdict"), [(10, "INTACT_ON_THE_LINE"), (11, "NOT_FOUND")]
)
def test_an_open_frame_must_hold_95_percent_of_the_reference(
    changes: int, verdict: str
) -> None:
    contig_dna = on_the_line(gene(mutated(changes)))

    result = check_circular_join(contig_dna, PROTEIN, GeneticCode.STANDARD)

    assert ORGANELLE_MATCHED == 0.95
    assert result.verdict == verdict
    assert result.best_linear == 200 - changes


def test_only_runs_of_four_residues_or_more_count() -> None:
    scattered = "".join(
        residue if k % 4 != 3 else ("A" if residue != "A" else "G")
        for k, residue in enumerate(PROTEIN)
    )
    contig_dna = on_the_line(gene(PROTEIN[:100]) + "C" * 30 + scattered[100:])

    result = check_circular_join(contig_dna, PROTEIN, GeneticCode.STANDARD)

    assert ORGANELLE_WORD == 4
    assert result.best_linear == 100


def test_an_empty_reference_is_refused() -> None:
    with pytest.raises(ValueError, match="the reference protein is empty"):
        check_circular_join(SPACER, "", GeneticCode.STANDARD)

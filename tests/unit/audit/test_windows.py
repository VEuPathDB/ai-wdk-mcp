from tests._support.proteins import PROTEIN, back_translate

from veupathdb_mcp.audit.codes import GeneticCode, reverse_complement
from veupathdb_mcp.audit.windows import STEP, WINDOW, best_identity, confirm_in_dna


def test_identity_is_the_best_ungapped_window_match() -> None:
    assert best_identity(PROTEIN[40:60], PROTEIN) == 1.0
    assert best_identity("WWWWWWWWWWWWWWWWWWWW", PROTEIN) < 0.35


def test_a_window_longer_than_the_target_has_no_identity() -> None:
    assert best_identity(PROTEIN[:20], PROTEIN[:10]) == 0.0


def test_a_segment_missing_from_the_model_but_encoded_in_the_dna_is_genome() -> None:
    dna = "CCCC" + back_translate(PROTEIN) + "CCCC"
    model = PROTEIN[:60] + PROTEIN[120:]
    result = confirm_in_dna(PROTEIN, [model], dna, "+", GeneticCode.STANDARD)
    assert result.track == "MMMMMMGGGGGMMMMMMMM"
    assert result.counts == {"model": 14, "genome_same_strand": 5}


def test_a_segment_on_the_other_strand_is_not_the_gene_strand() -> None:
    dna = reverse_complement(back_translate(PROTEIN))
    result = confirm_in_dna(PROTEIN, [PROTEIN[:30]], dna, "+", GeneticCode.STANDARD)
    assert result.track == "MMggggggggggggggggg"
    assert result.counts == {"model": 2, "genome_other_strand": 17}


def test_a_minus_strand_gene_reads_its_own_strand() -> None:
    dna = reverse_complement(back_translate(PROTEIN))
    result = confirm_in_dna(PROTEIN, [], dna, "-", GeneticCode.STANDARD)
    assert result.track == "G" * 19
    assert "genome_other_strand" not in result.counts


def test_a_window_between_missing_and_found_is_weak() -> None:
    start = 5 * STEP
    model = PROTEIN[start : start + 8] + "#" * (WINDOW - 8)
    assert best_identity(PROTEIN[start : start + WINDOW], model) == 0.4
    result = confirm_in_dna(PROTEIN, [model], "C" * 600, "+", GeneticCode.STANDARD)
    assert result.track == "....." + "w" + "." * 13
    assert result.track.index("w") == 5


def test_dna_that_does_not_encode_the_protein_is_absent() -> None:
    result = confirm_in_dna(PROTEIN, [], "C" * 600, "+", GeneticCode.STANDARD)
    assert result.track == "." * 19
    assert result.counts == {"absent": 19}

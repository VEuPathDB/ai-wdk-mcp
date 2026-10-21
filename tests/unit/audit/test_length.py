import pytest
from tests._support.proteins import PROTEIN, back_translate

from veupathdb_mcp.audit.codes import GeneticCode, reverse_complement
from veupathdb_mcp.audit.length import DnaWindow, LengthCheck, check_length

STANDARD = GeneticCode.STANDARD
SHORT_MODEL = PROTEIN[:60] + PROTEIN[120:]


def window(dna: str, *, strand: str = "+", edge: bool = False) -> DnaWindow:
    return DnaWindow.model_validate(
        {"sequence": dna, "strand": strand, "at_contig_edge": edge}
    )


def encoded() -> str:
    return "CCCC" + back_translate(PROTEIN) + "CCCC"


def test_a_segment_the_genome_encodes_on_the_gene_strand() -> None:
    result = check_length(PROTEIN, [SHORT_MODEL], window(encoded()), STANDARD)

    assert result.verdict == "GENOME_ENCODES"
    assert result.windows == 19
    assert result.counts == {"model": 14, "genome_same_strand": 5}
    assert result.track == "MMMMMMGGGGGMMMMMMMM"
    assert result.ns_in_window == 0


def test_a_minus_strand_gene_is_confirmed_on_its_strand() -> None:
    dna = reverse_complement(encoded())
    result = check_length(PROTEIN, [SHORT_MODEL], window(dna, strand="-"), STANDARD)

    assert result.verdict == "GENOME_ENCODES"
    assert result.counts == {"model": 14, "genome_same_strand": 5}
    assert result.track == "MMMMMMGGGGGMMMMMMMM"


def test_a_segment_only_on_the_other_strand_is_not_genome_encodes() -> None:
    dna = (
        back_translate(PROTEIN[:60])
        + reverse_complement(back_translate(PROTEIN[60:120]))
        + back_translate(PROTEIN[120:])
    )
    result = check_length(PROTEIN, [SHORT_MODEL], window(dna), STANDARD)

    assert result.counts == {"model": 14, "genome_other_strand": 5}
    assert result.track == "MMMMMMgggggMMMMMMMM"
    assert result.verdict == "ABSENT"


def test_a_segment_over_ns_is_assembly() -> None:
    dna = (
        "CCCC"
        + back_translate(PROTEIN[:60])
        + "N" * 200
        + back_translate(PROTEIN[120:])
        + "CCCC"
    )
    result = check_length(PROTEIN, [SHORT_MODEL], window(dna), STANDARD)

    assert result.verdict == "ASSEMBLY"
    assert result.ns_in_window == 200


def test_a_missing_segment_near_a_contig_end_is_assembly() -> None:
    dna = back_translate(PROTEIN[:60]) + "C" * 600
    result = check_length(PROTEIN, [PROTEIN[:60]], window(dna, edge=True), STANDARD)

    assert result.verdict == "ASSEMBLY"
    assert result.at_contig_edge


def test_a_segment_the_genome_lacks_is_absent() -> None:
    dna = back_translate(PROTEIN[:60]) + "C" * 600
    result = check_length(PROTEIN, [PROTEIN[:60]], window(dna), STANDARD)
    assert result.verdict == "ABSENT"


def test_two_windows_on_the_gene_strand_are_too_few_to_encode() -> None:
    dna = back_translate(PROTEIN[:110]) + "C" * 600
    result = check_length(PROTEIN, [PROTEIN[:100]], window(dna), STANDARD)

    assert result.counts["genome_same_strand"] == 2
    assert result.verdict == "ABSENT"


def test_windows_on_the_gene_strand_under_half_the_missing_do_not_encode() -> None:
    dna = back_translate(PROTEIN[:120]) + "C" * 600
    result = check_length(PROTEIN, [PROTEIN[:100]], window(dna), STANDARD)

    assert result.counts == {"model": 9, "genome_same_strand": 3, "absent": 7}
    assert result.verdict == "ABSENT"


def test_windows_on_the_gene_strand_at_half_the_missing_encode() -> None:
    dna = back_translate(PROTEIN[:140]) + "C" * 600
    result = check_length(PROTEIN, [PROTEIN[:100]], window(dna), STANDARD)

    assert result.counts == {"model": 9, "genome_same_strand": 5, "absent": 5}
    assert result.verdict == "GENOME_ENCODES"


def test_a_model_that_holds_every_window_is_not_short() -> None:
    result = check_length(PROTEIN, [PROTEIN], window("C" * 600), STANDARD)

    assert result.verdict == "NOT_SHORT"
    assert result.counts == {"model": 19}


def test_two_parts_covering_the_reference_are_a_split() -> None:
    parts = [PROTEIN[:100], PROTEIN[100:]]
    result = check_length(PROTEIN, parts, window(encoded()), STANDARD)

    assert result.verdict == "SPLIT_CONFIRMED"
    assert result.counts == {"part1": 9, "genome_same_strand": 1, "part2": 9}
    assert result.track == "1" * 9 + "G" + "2" * 9


def test_a_part_that_holds_too_few_windows_is_an_unclear_split() -> None:
    parts = [PROTEIN[:170], PROTEIN[170:]]
    result = check_length(PROTEIN, parts, window(encoded()), STANDARD)

    assert result.counts == {"part1": 16, "genome_same_strand": 1, "part2": 2}
    assert result.track == "1" * 16 + "G22"
    assert result.verdict == "SPLIT_UNCLEAR"


def test_parts_that_cover_too_little_of_the_reference_are_an_unclear_split() -> None:
    parts = [PROTEIN[:50], PROTEIN[150:]]
    result = check_length(PROTEIN, parts, window(encoded()), STANDARD)

    assert result.counts == {"part1": 4, "genome_same_strand": 11, "part2": 4}
    assert result.track == "1111" + "G" * 11 + "2222"
    assert result.verdict == "SPLIT_UNCLEAR"


def test_the_window_counts_its_ns_in_either_case() -> None:
    assert window("ACGTNNnn").ns == 4


def test_three_models_are_refused() -> None:
    with pytest.raises(ValueError, match="one model or two parts"):
        check_length(PROTEIN, [PROTEIN] * 3, window(encoded()), STANDARD)


def test_the_check_serializes_camel_case() -> None:
    result = check_length(PROTEIN, [SHORT_MODEL], window(encoded()), STANDARD)
    assert {"nsInWindow", "atContigEdge", "verdict", "track"} <= set(
        result.model_dump(by_alias=True)
    )


def test_a_check_that_read_no_genome_states_no_dna_facts() -> None:
    result = LengthCheck.not_checked()

    assert result.verdict == "NOT_CHECKED"
    assert (result.windows, result.counts, result.track) == (0, {}, "")
    assert (result.ns_in_window, result.at_contig_edge) == (None, None)


def test_a_check_that_read_the_genome_states_its_dna_facts() -> None:
    with pytest.raises(ValueError, match="states its window facts"):
        LengthCheck(
            verdict="ABSENT",
            windows=19,
            counts={"absent": 19},
            track="." * 19,
            ns_in_window=None,
            at_contig_edge=None,
        )

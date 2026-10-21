import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from veupathdb_mcp.audit.codes import GeneticCode, reverse_complement
from veupathdb_mcp.audit.selenocysteine import (
    SecCheck,
    SecVerdict,
    check_sec_stop,
    sec_aligned,
    sec_tail,
)

FIXTURES = Path(__file__).parent / "fixtures"
CODON = {
    "M": "ATG",
    "A": "GCT",
    "C": "TGT",
    "G": "GGC",
    "K": "AAA",
    "L": "CTG",
    "V": "GTT",
}


def load(name: str) -> dict[str, str]:
    return json.loads((FIXTURES / name).read_text())


def coding(protein: str) -> str:
    return "".join(CODON[residue] for residue in protein)


def test_the_gt1_selk_model_stops_at_its_sec_codon() -> None:
    gt1 = load("tgonGT1_selk.json")
    me49 = load("tgonME49_selk.json")
    result = check_sec_stop(
        gt1["model_protein"],
        me49["reference_protein"],
        gt1["sequence"],
        "+",
        GeneticCode.STANDARD,
    )
    assert result.verdict == "STOPS_AT_SEC"
    assert result.after_model_end.startswith("*G*")
    assert result.reference_tail == "UG"


def test_the_recorded_proteins_are_the_selk_models() -> None:
    gt1 = load("tgonGT1_selk.json")
    me49 = load("tgonME49_selk.json")
    assert len(gt1["model_protein"]) == 131
    assert "U" not in gt1["model_protein"]
    assert len(me49["reference_protein"]) == 133
    assert me49["reference_protein"].endswith("NFVCGGGGUG")
    assert me49["model_protein"] == me49["reference_protein"]


def test_a_model_that_contains_sec_is_not_flagged() -> None:
    me49 = load("tgonME49_selk.json")
    result = check_sec_stop(
        me49["reference_protein"],
        me49["reference_protein"],
        "",
        "+",
        GeneticCode.STANDARD,
    )
    assert result.verdict == "CONTAINS_SEC"


def test_a_model_ending_before_a_non_tga_stop_is_not_at_sec() -> None:
    reference = "MAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAUG"
    dna = "ATG" + "GCT" * 30 + "TAA" + "GGT" + "TAA"
    result = check_sec_stop("M" + "A" * 30, reference, dna, "+", GeneticCode.STANDARD)
    assert result.verdict == "NOT_AT_SEC"
    assert result.after_model_end.startswith("*G*")


def test_a_minus_strand_model_is_read_on_its_own_strand() -> None:
    gene = coding("MKLVCGGGG") + "TGA" + "GGT" + "TAA" + "GCTGCT"
    dna = "GCT" + reverse_complement(gene) + "AA"
    result = check_sec_stop("MKLVCGGGG", "MKLVCGGGGUG", dna, "-", GeneticCode.STANDARD)
    assert result.verdict == "STOPS_AT_SEC"
    assert result.after_model_end.startswith("*G*AA")


def test_a_long_tail_after_sec_is_compared_in_full() -> None:
    tail = "ACGKLV" * 4
    gene = coding("MKLVCGG") + "TGA" + coding(tail) + "TAA"
    result = check_sec_stop(
        "MKLVCGG", "MKLVCGGU" + tail, gene, "+", GeneticCode.STANDARD
    )
    assert result.verdict == "STOPS_AT_SEC"
    assert result.reference_tail == "U" + tail


def test_a_tail_that_differs_from_the_reference_is_not_at_sec() -> None:
    gene = coding("MKLVCGGGG") + "TGA" + coding("AA") + "TAA"
    result = check_sec_stop("MKLVCGGGG", "MKLVCGGGGUG", gene, "+", GeneticCode.STANDARD)
    assert result.verdict == "NOT_AT_SEC"
    assert result.after_model_end == "*AA*"


def test_a_model_absent_from_the_region_is_not_found() -> None:
    result = check_sec_stop(
        "MKLVCGGGG", "MKLVCGGGGUG", "A" * 90, "+", GeneticCode.STANDARD
    )
    assert result.verdict == "MODEL_NOT_FOUND"
    assert result.after_model_end == ""


def test_a_reference_without_sec_is_refused() -> None:
    gene = coding("MKLVCGGGG") + "TGA" + "GGT" + "TAA"
    with pytest.raises(ValueError, match="no selenocysteine"):
        check_sec_stop("MKLVCGGGG", "MKLVCGGGGG", gene, "+", GeneticCode.STANDARD)


def test_the_tail_of_a_reference_starts_at_its_first_sec() -> None:
    assert sec_tail("MKLVCUGGUG") == "UGGUG"
    assert sec_tail("MKLVCGG") == ""


def test_a_second_sec_in_the_tail_reads_as_the_stop_the_genome_shows() -> None:
    gene = coding("MKLVCGGGG") + "TGA" + coding("G") + "TGA" + coding("G") + "TAA"
    result = check_sec_stop(
        "MKLVCGGGG", "MKLVCGGGGUGUG", gene, "+", GeneticCode.STANDARD
    )
    assert result.verdict == "STOPS_AT_SEC"
    assert result.reference_tail == "UGUG"


def test_an_empty_model_is_not_found() -> None:
    gene = coding("MKLVCGGGG") + "TGA" + "GGT" + "TAA"
    result = check_sec_stop("", "MKLVCGGGGUG", gene, "+", GeneticCode.STANDARD)
    assert result.verdict == "MODEL_NOT_FOUND"
    assert result.after_model_end == ""


def test_a_model_shorter_than_the_anchor_is_not_found() -> None:
    gene = coding("MKLVCGGGG") + "TGA" + "GGT" + "TAA"
    result = check_sec_stop("CGGGG", "MKLVCGGGGUG", gene, "+", GeneticCode.STANDARD)
    assert result.verdict == "MODEL_NOT_FOUND"
    assert result.after_model_end == ""


def test_a_later_copy_of_the_anchor_is_tried_after_an_earlier_one() -> None:
    gene = coding("MKLVCGGGG") + "GCT" + coding("KLVCGGGG") + "TGA" + "GGT" + "TAA"
    result = check_sec_stop("MKLVCGGGG", "MKLVCGGGGUG", gene, "+", GeneticCode.STANDARD)
    assert result.verdict == "STOPS_AT_SEC"
    assert result.after_model_end == "*G*"


def test_the_gt1_selk_tail_is_identical_and_its_end_aligns_before_sec() -> None:
    gt1 = load("tgonGT1_selk.json")
    me49 = load("tgonME49_selk.json")
    result = check_sec_stop(
        gt1["model_protein"],
        me49["reference_protein"],
        gt1["sequence"],
        "+",
        GeneticCode.STANDARD,
    )
    assert (result.tail_identity, result.sec_aligned) == (1.0, True)


def test_a_tail_differing_in_one_residue_of_five_stops_at_sec() -> None:
    gene = coding("MKLVCGGGG") + "TGA" + coding("AKLVA") + "TAA"
    result = check_sec_stop(
        "MKLVCGGGG", "MKLVCGGGGUAKLVC", gene, "+", GeneticCode.STANDARD
    )
    assert result.verdict == "STOPS_AT_SEC"
    assert (result.tail_identity, result.sec_aligned) == (0.8, True)


def test_a_tail_differing_in_two_residues_of_five_is_not_at_sec() -> None:
    gene = coding("MKLVCGGGG") + "TGA" + coding("AKLAA") + "TAA"
    result = check_sec_stop(
        "MKLVCGGGG", "MKLVCGGGGUAKLVC", gene, "+", GeneticCode.STANDARD
    )
    assert result.verdict == "NOT_AT_SEC"
    assert result.tail_identity == 0.6


def test_a_stop_in_the_genome_tail_ends_the_comparison() -> None:
    gene = coding("MKLVCGGGG") + "TGA" + coding("AK") + "TAA" + coding("VC") + "TAA"
    result = check_sec_stop(
        "MKLVCGGGG", "MKLVCGGGGUAKLVC", gene, "+", GeneticCode.STANDARD
    )
    assert result.verdict == "NOT_AT_SEC"
    assert result.tail_identity == 0.4


def test_a_tga_stop_before_the_reference_sec_is_not_at_sec() -> None:
    gene = coding("MKLVCGGGG") + "TGA" + coding("G") + "TAA"
    result = check_sec_stop(
        "MKLVCGGGG", "MKLVCGGGGAAAAUG", gene, "+", GeneticCode.STANDARD
    )
    assert result.verdict == "NOT_AT_SEC"
    assert (result.tail_identity, result.sec_aligned) == (1.0, False)


def test_a_model_that_contains_sec_compares_no_tail() -> None:
    me49 = load("tgonME49_selk.json")
    result = check_sec_stop(
        me49["reference_protein"],
        me49["reference_protein"],
        "",
        "+",
        GeneticCode.STANDARD,
    )
    assert (result.tail_identity, result.sec_aligned) == (None, None)


@pytest.mark.parametrize(
    ("identity", "aligned"), [(0.79, True), (1.0, False), (None, True), (1.0, None)]
)
def test_stops_at_sec_needs_an_aligned_end_and_a_matching_tail(
    identity: float | None, aligned: bool | None
) -> None:
    with pytest.raises(ValidationError):
        SecCheck(
            verdict="STOPS_AT_SEC",
            after_model_end="*G*",
            reference_tail="UG",
            tail_identity=identity,
            sec_aligned=aligned,
        )


@pytest.mark.parametrize(
    ("verdict", "identity", "aligned"),
    [
        ("NOT_AT_SEC", None, True),
        ("MODEL_NOT_FOUND", 1.0, True),
        ("CONTAINS_SEC", None, False),
    ],
)
def test_a_tail_is_served_only_where_the_model_end_was_found(
    verdict: SecVerdict, identity: float | None, aligned: bool | None
) -> None:
    with pytest.raises(ValidationError):
        SecCheck(
            verdict=verdict,
            after_model_end="",
            reference_tail="UG",
            tail_identity=identity,
            sec_aligned=aligned,
        )


def test_a_model_end_that_differs_from_the_reference_still_aligns_before_sec() -> None:
    assert sec_aligned("MKLVCAAAV", "MKLVCAAAAUGGGGUCC")
    assert sec_aligned("MKLVCAAAA", "MKLVCAAAAUGGGGUCC")


def test_a_model_end_far_past_its_last_match_does_not_align() -> None:
    assert not sec_aligned("MKLVCQWERTY", "MKLVCAAAAAAUG")


def test_a_reference_with_two_sec_aligns_the_end_before_the_first() -> None:
    gene = coding("MKLVCAAAA") + "TGA" + coding("GGGG") + "TGA" + coding("CC") + "TAA"
    result = check_sec_stop(
        "MKLVCAAAA", "MKLVCAAAAUGGGGUCC", gene, "+", GeneticCode.STANDARD
    )
    assert (result.verdict, result.sec_aligned, result.tail_identity) == (
        "STOPS_AT_SEC",
        True,
        1.0,
    )
    assert not sec_aligned("MKLVCAAAACGGGG", "MKLVCAAAAUGGGGUCC")


def test_a_model_shorter_than_the_anchor_serves_its_alignment_and_no_tail() -> None:
    result = check_sec_stop("MKLVC", "MKLVCUG", "A" * 90, "+", GeneticCode.STANDARD)
    assert (result.verdict, result.sec_aligned, result.tail_identity) == (
        "MODEL_NOT_FOUND",
        True,
        None,
    )

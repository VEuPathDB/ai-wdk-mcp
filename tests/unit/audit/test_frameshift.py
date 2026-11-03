from itertools import pairwise

import pytest
from tests._support.nf54_frameshift import (
    MODEL_PROTEIN,
    REFERENCE_PROTEIN,
    model_coding,
    run_offset,
)
from tests._support.proteins import PROTEIN, back_translate

from veupathdb_mcp.audit import frameshift
from veupathdb_mcp.audit.codes import GeneticCode, reverse_complement, translate
from veupathdb_mcp.audit.frameshift import (
    FrameChange,
    ReferenceRun,
    RepeatRun,
    SplicePair,
    flanked_span,
    repeat_at,
)
from veupathdb_mcp.audit.length import LengthCheck, check_length
from veupathdb_mcp.audit.variant_calls import VariantCalls
from veupathdb_mcp.audit.windows import (
    DnaWindow,
    GenomeSource,
    SegmentTrack,
    WindowHit,
    confirm_in_dna,
)

STANDARD = GeneticCode.STANDARD
SOURCE = GenomeSource(
    site="constructed_site", organism="constructed_genome", seqid="constructed_seq"
)
CUT = 60
START = 1001


def window(dna: str, *, strand: str = "+") -> DnaWindow:
    return DnaWindow.model_validate(
        {
            "source": SOURCE,
            "start": START,
            "sequence": dna,
            "strand": strand,
            "at_contig_edge": False,
        }
    )


def read_to_stop(coding: str) -> str:
    protein = translate(coding, STANDARD)
    assert "*" in protein
    return protein[: protein.index("*")]


def cut_by(insert: str, *, at: int = CUT) -> tuple[str, str]:
    coding = back_translate(PROTEIN[:at]) + insert + back_translate(PROTEIN[at:])
    return "CCCC" + coding + "CCCC", read_to_stop(coding)


def constructed_change(**changes: object) -> FrameChange:
    return FrameChange.model_validate(
        {
            "source": SOURCE,
            "strand": "+",
            "start": 10,
            "end": 12,
            "frame_before": 0,
            "frame_after": 1,
            "shift": 1,
            "reference_residues": (5, 6),
            "run": None,
            "splice_pair": None,
            "steps_between": 1,
            **changes,
        }
    )


def slip_reference(at: int = CUT) -> str:
    return PROTEIN[:at] + "KKKK" + PROTEIN[at:]


def slipped(extra: str = "A", at: int = CUT) -> tuple[str, str, str]:
    coding = (
        back_translate(PROTEIN[:at]) + "AAA" * 4 + extra + back_translate(PROTEIN[at:])
    )
    return "CCCC" + coding + "CCCC", read_to_stop(coding), slip_reference(at)


def checked_verdict(dna: str, model: str, reference: str = PROTEIN) -> LengthCheck:
    return check_length(reference, [model], window(dna), STANDARD)


def test_each_located_window_records_its_base() -> None:
    dna = "C" + back_translate(PROTEIN[:60]) + "GG" + back_translate(PROTEIN[60:])

    track = confirm_in_dna(PROTEIN, [PROTEIN[:60]], dna, "+", STANDARD)

    assert track.states[:5] == ["model"] * 5
    assert track.states[6:] == ["genome_same_strand"] * 13
    placed = [None if hit is None else hit.base % 3 for hit in track.hits]
    assert placed[:5] == [1] * 5
    assert placed[7:] == [0] * 12


def test_a_window_on_the_other_strand_records_no_place() -> None:
    dna = reverse_complement(back_translate(PROTEIN))

    track = confirm_in_dna(PROTEIN, [PROTEIN[:30]], dna, "+", STANDARD)

    assert track.counts == {"model": 2, "genome_other_strand": 17}
    assert track.hits == [None] * 19


def test_a_one_base_insertion_in_a_poly_a_run_is_a_frameshift_at_that_run() -> None:
    coding = model_coding()
    dna = "CC" + coding

    result = checked_verdict(dna, MODEL_PROTEIN, REFERENCE_PROTEIN)

    assert result.verdict == "FRAMESHIFT"
    change = result.frame_changes[0]
    first = START + 2 + run_offset(coding)
    assert change.run == RepeatRun(unit="A", bases=29, start=first, end=first + 28)
    assert change.shift == 1
    assert change.source == SOURCE
    assert change.splice_pair is None
    assert first <= change.start <= change.end <= first + 40
    assert change.frame_before != change.frame_after


def test_a_minus_strand_gene_names_its_run_on_the_genome() -> None:
    dna = reverse_complement("CC" + model_coding())

    result = check_length(
        REFERENCE_PROTEIN, [MODEL_PROTEIN], window(dna, strand="-"), STANDARD
    )

    assert result.verdict == "FRAMESHIFT"
    run = result.frame_changes[0].run
    assert run is not None
    assert (run.unit, run.bases) == ("A", 29)
    assert dna[run.start - START : run.end - START + 1] == "T" * 29


def test_a_gap_of_ns_in_the_same_frame_is_assembly() -> None:
    dna = (
        "CCCC"
        + back_translate(PROTEIN[:CUT])
        + "N" * 99
        + back_translate(PROTEIN[CUT + 33 :])
    )

    assert checked_verdict(dna, PROTEIN[:CUT]).verdict == "ASSEMBLY"


def test_a_gap_of_ns_with_every_residue_after_it_is_assembly() -> None:
    dna = (
        "CCCC"
        + back_translate(PROTEIN[:CUT])
        + "N" * 99
        + back_translate(PROTEIN[CUT:])
    )

    assert checked_verdict(dna, PROTEIN[:CUT]).verdict == "ASSEMBLY"


def test_a_gap_of_ns_in_another_frame_is_assembly_with_its_change_stated() -> None:
    dna, model = cut_by("NNNN")

    result = checked_verdict(dna, model)

    assert result.verdict == "ASSEMBLY"
    assert [change.shift for change in result.frame_changes] == [4]


def test_an_n_outside_the_parts_is_no_gap_between_them() -> None:
    dna, model, reference = slipped()

    assert checked_verdict(dna + "NNNN", model, reference).verdict == "FRAMESHIFT"
    assert checked_verdict("NNNN" + dna, model, reference).verdict == "FRAMESHIFT"


def test_a_clean_truncation_in_the_open_frame_is_genome_encodes() -> None:
    dna = "CCCC" + back_translate(PROTEIN) + "CCCC"

    result = checked_verdict(dna, PROTEIN[:CUT])

    assert result.verdict == "GENOME_ENCODES"
    assert result.frame_changes == []


def test_a_start_that_is_missing_in_the_open_frame_is_genome_encodes() -> None:
    dna = "CCCC" + back_translate(PROTEIN) + "CCCC"

    assert checked_verdict(dna, PROTEIN[120:]).verdict == "GENOME_ENCODES"


def test_a_frame_change_past_an_open_stretch_is_stated_under_genome_encodes() -> None:
    coding = back_translate(PROTEIN[:120]) + "G" + back_translate(PROTEIN[120:])

    result = checked_verdict("CCCC" + coding + "CCCC", PROTEIN[:40])

    assert result.verdict == "GENOME_ENCODES"
    assert [change.shift for change in result.frame_changes] == [1]
    assert result.frame_changes[0].model_goes_on is False


def test_a_three_base_change_in_the_open_frame_is_genome_encodes() -> None:
    reference = PROTEIN[:CUT] + "GGGGGG" + PROTEIN[CUT:]
    coding = (
        back_translate(reference[: CUT + 6])
        + "GGT"
        + back_translate(reference[CUT + 6 :])
    )

    result = checked_verdict("CCCC" + coding, PROTEIN[:CUT], reference)

    assert result.verdict == "GENOME_ENCODES"


def test_a_stop_between_the_model_and_the_part_in_its_frame_is_other_frame() -> None:
    coding = back_translate(PROTEIN)
    edited = coding[: 3 * CUT] + "TAA" + coding[3 * CUT + 3 :]

    result = checked_verdict("CCCC" + edited, PROTEIN[:CUT])

    assert result.verdict == "OTHER_FRAME"
    assert result.frame_changes == []


def test_a_one_base_change_with_no_run_is_other_frame() -> None:
    dna, model = cut_by("G")

    result = checked_verdict(dna, model)

    assert result.verdict == "OTHER_FRAME"
    assert [change.shift for change in result.frame_changes] == [1]
    assert [change.run for change in result.frame_changes] == [None]
    assert result.frame_changes[0].run_explains_shift is False


def test_a_one_base_change_in_a_run_is_a_frameshift() -> None:
    dna, model, reference = slipped()

    result = checked_verdict(dna, model, reference)

    assert result.verdict == "FRAMESHIFT"
    change = result.frame_changes[0]
    assert change.shift == 1
    assert change.run_explains_shift is True
    assert change.run is not None
    assert (change.run.unit, change.run.bases) == ("A", 16)


def test_a_two_base_shift_is_a_frameshift() -> None:
    dna, model, reference = slipped("AA")

    assert checked_verdict(dna, model, reference).verdict == "FRAMESHIFT"


def test_a_deleted_base_is_a_frameshift_with_a_negative_shift() -> None:
    edited = back_translate(PROTEIN[:CUT]) + "A" * 11 + back_translate(PROTEIN[CUT:])

    result = checked_verdict("CCCC" + edited, read_to_stop(edited), slip_reference())

    assert result.verdict == "FRAMESHIFT"
    assert result.frame_changes[0].shift == -1


@pytest.mark.parametrize("insert", ["GCCC", "GCCCC", "GCCCCCC", "GCCCCCCCCC"])
def test_a_shift_outside_the_limit_is_other_frame(insert: str) -> None:
    dna, model = cut_by(insert)

    result = checked_verdict(dna, model)

    assert result.verdict == "OTHER_FRAME"
    assert result.frame_changes[0].shift == len(insert)


def test_copies_of_a_run_unit_explain_their_shift() -> None:
    left = back_translate(PROTEIN[:CUT])
    right = back_translate(PROTEIN[CUT:])
    reference = translate(left + "GT" * 12 + "A" + right[1:], STANDARD)
    edited = left + "GT" * 13 + "A" + right[1:]

    result = checked_verdict("CCCC" + edited, read_to_stop(edited), reference)

    assert result.verdict == "FRAMESHIFT"
    change = result.frame_changes[0]
    assert change.shift == 2
    assert change.run is not None
    assert (len(change.run.unit), change.run.bases) == (2, 26)


def test_more_copies_of_a_run_unit_than_two_are_other_frame() -> None:
    left = back_translate(PROTEIN[:CUT])
    right = back_translate(PROTEIN[CUT:])
    reference = translate(left + "GATTC" * 6 + "A" + right[1:], STANDARD)
    edited = left + "GATTC" * 10 + "A" + right[1:]

    result = checked_verdict("CCCC" + edited, read_to_stop(edited), reference)

    assert result.verdict == "OTHER_FRAME"
    assert result.frame_changes[0].shift == 20


@pytest.mark.parametrize(
    ("length", "lacking", "shift"),
    [
        (34, 6, 16),
        (23, 1, 20),
        (40, 7, 19),
        (52, 12, 16),
        (80, 25, 5),
        (95, 30, 5),
        (100, 27, 19),
        (100, 31, 7),
    ],
)
def test_a_true_intron_is_other_frame_and_names_its_splice_pair(
    length: int, lacking: int, shift: int
) -> None:
    dna = (
        "CCCC"
        + back_translate(PROTEIN[:CUT])
        + "GT"
        + "T" * (length - 4)
        + "AG"
        + back_translate(PROTEIN[CUT + lacking :])
    )

    result = checked_verdict(dna, PROTEIN[:CUT])

    assert result.verdict == "OTHER_FRAME"
    assert result.frame_changes[0].shift == shift
    assert result.frame_changes[0].run is None
    pair = result.frame_changes[0].splice_pair
    assert pair is not None
    assert pair.motif == "GT..AG"
    assert pair.acceptor - pair.donor + 1 == length


def quiet_cut() -> int:
    coding = back_translate(PROTEIN)
    return next(
        at
        for at in range(CUT, 150)
        if "GT" not in coding[3 * at - 9 : 3 * at + 3]
        and "GC" not in coding[3 * at - 9 : 3 * at + 3]
    )


def intron_cut(between: str, *, quiet: bool = False) -> tuple[str, str]:
    at = quiet_cut() if quiet else CUT
    coding = (
        back_translate(PROTEIN[:at])
        + between
        + back_translate(PROTEIN[at + (len(between) - 1) // 3 :])
    )
    return "CCCC" + coding + "CCCC", read_to_stop(coding)


def test_a_one_base_shift_with_a_splice_pair_at_the_change_is_other_frame() -> None:
    dna, model = intron_cut("GTTTAACCCTCCCTCCCTCCAG")

    result = checked_verdict(dna, model)

    assert result.verdict == "OTHER_FRAME"
    assert result.frame_changes[0].shift == 1
    assert result.frame_changes[0].splice_pair is not None


def test_the_same_shift_with_no_acceptor_has_no_pair() -> None:
    dna, model = intron_cut("GTTTAACCCTCCCTCCCTCCGG")

    assert checked_verdict(dna, model).frame_changes[0].splice_pair is None


def test_the_same_shift_with_no_donor_has_no_pair() -> None:
    dna, model = intron_cut("CCATAACCCTCCCTCCCTCCAG", quiet=True)

    assert checked_verdict(dna, model).frame_changes[0].splice_pair is None


def test_a_pair_inside_the_stretch_away_from_its_ends_is_no_splice_pair() -> None:
    dna, model = intron_cut("CCCTAAGTCCCTCCCTAGCCCC" + "CCC")

    result = checked_verdict(dna, model)

    assert result.frame_changes[0].splice_pair is None


def diverged(share: int, reference: str) -> str:
    return "".join(
        "G" if residue and residue % share == 0 and letter != "G" else letter
        for residue, letter in enumerate(reference)
    )


@pytest.mark.parametrize(("share", "lost"), [(5, 1), (4, 0), (3, 0)])
def test_a_one_base_change_stands_against_a_diverged_reference(
    share: int, lost: int
) -> None:
    held = 0
    cuts = range(50, 130, 3)
    for at in cuts:
        dna, model, reference = slipped(at=at)
        held += (
            checked_verdict(dna, model, diverged(share, reference)).verdict
            == "FRAMESHIFT"
        )

    assert held == len(cuts) - lost


def test_a_one_base_change_before_the_model_is_a_frameshift() -> None:
    dna, _, reference = slipped(at=120)

    result = checked_verdict(dna, PROTEIN[120:], reference)

    assert result.verdict == "FRAMESHIFT"
    assert result.frame_changes[0].shift == 1
    assert result.frame_changes[0].model_goes_on is True


def test_a_model_that_goes_on_past_the_change_is_a_frameshift_and_says_so() -> None:
    dna, _, reference = slipped(at=80)

    result = checked_verdict(dna, PROTEIN[:80] + PROTEIN[130:], reference)

    assert result.verdict == "FRAMESHIFT"
    assert result.frame_changes[0].model_goes_on is True


def test_a_model_with_nothing_past_the_change_says_so() -> None:
    dna, model, reference = slipped()

    assert (
        checked_verdict(dna, model, reference).frame_changes[0].model_goes_on is False
    )


def test_a_change_the_model_spans_is_not_a_frame_change() -> None:
    dna, _ = cut_by("GTTG")

    result = checked_verdict(dna, PROTEIN[:150])

    assert result.verdict == "GENOME_ENCODES"
    assert result.frame_changes == []


def test_parts_too_far_apart_are_other_frame() -> None:
    coding = (
        back_translate(PROTEIN[:CUT])
        + "A" * 13
        + "CC"
        + "TAA" * 40
        + "C"
        + back_translate(PROTEIN[CUT + 41 :])
    )

    result = checked_verdict("CCCC" + coding, read_to_stop(coding), slip_reference())

    assert result.verdict == "OTHER_FRAME"
    assert result.frame_changes[0].shift == 1
    assert result.frame_changes[0].run is not None
    assert result.frame_changes[0].run_explains_shift is False


def test_parts_with_windows_between_them_stay_a_frameshift() -> None:
    coding = (
        back_translate(PROTEIN[:CUT])
        + "A" * 13
        + "CC"
        + "TAA" * 20
        + "C"
        + back_translate(PROTEIN[CUT + 21 :])
    )

    result = checked_verdict("CCCC" + coding, read_to_stop(coding), slip_reference())

    assert result.verdict == "FRAMESHIFT"


def four_slips() -> tuple[str, str]:
    cuts = [0, 40, 80, 120, 150, len(PROTEIN)]
    parts = [PROTEIN[a:b] for a, b in pairwise(cuts)]
    return (
        ("A" * 13).join(back_translate(part) for part in parts),
        "KKKK".join(parts),
    )


def test_every_change_is_reported_up_to_the_cap() -> None:
    coding, reference = four_slips()

    result = checked_verdict("CCCC" + coding, read_to_stop(coding), reference)

    assert result.verdict == "FRAMESHIFT"
    assert [change.shift for change in result.frame_changes] == [1, 1, 1]
    assert [change.shift for change in result.unlisted_changes] == [1]
    assert frameshift.MAX_FRAME_CHANGES == 3


def test_an_n_between_two_parts_the_model_holds_is_no_gap() -> None:
    coding = back_translate(PROTEIN[:100]) + "N" * 27 + back_translate(PROTEIN[100:])

    assert checked_verdict("CCCC" + coding, PROTEIN[:150]).verdict == "GENOME_ENCODES"


def test_a_part_in_another_phase_is_not_in_the_open_frame() -> None:
    reference = PROTEIN[:CUT] + "KKKK" + "GA" * 40
    coding = back_translate(PROTEIN[:CUT]) + "A" * 13 + back_translate("GA" * 40)

    result = checked_verdict("CCCC" + coding, reference[:CUT], reference)

    assert "*" not in translate(coding[3 * CUT + 13 : 3 * CUT + 180], STANDARD)
    assert result.verdict == "FRAMESHIFT"


def test_a_slip_is_listed_before_a_long_jump_it_follows() -> None:
    coding = (
        back_translate(PROTEIN[:40])
        + "GCCCC"
        + back_translate(PROTEIN[40:100])
        + "A" * 13
        + back_translate(PROTEIN[100:])
    )

    result = checked_verdict("CCCC" + coding, PROTEIN[:40], slip_reference(100))

    assert result.verdict == "FRAMESHIFT"
    assert [change.shift for change in result.frame_changes] == [1, 5]


def test_a_splice_pair_that_would_not_leave_the_later_frame_is_no_pair() -> None:
    dna, model = intron_cut("CGTTAACCCTCCCTCCCTCCAG", quiet=True)

    assert checked_verdict(dna, model).frame_changes[0].splice_pair is None


def test_an_intron_the_model_spans_is_not_reported_as_a_change() -> None:
    exons = back_translate(PROTEIN[:120]) + "A" * 13 + back_translate(PROTEIN[120:])
    read_on = read_to_stop(exons)
    dna = "CCCC" + back_translate(PROTEIN[:60]) + "T" * 100 + exons[3 * 60 :]

    result = checked_verdict(dna, read_on, slip_reference(120))

    assert result.verdict == "FRAMESHIFT"
    assert [change.shift for change in result.frame_changes] == [1]


def test_a_three_base_jump_is_listed_and_the_reading_frame_holds() -> None:
    reference = PROTEIN[:CUT] + "GGGGGG" + PROTEIN[CUT:]
    coding = (
        back_translate(reference[: CUT + 6])
        + "GGT"
        + back_translate(reference[CUT + 6 :])
    )

    result = checked_verdict("CCCC" + coding, PROTEIN[:CUT], reference)

    assert result.verdict == "GENOME_ENCODES"
    assert [change.shift for change in result.frame_changes] == [3]
    assert result.frame_changes[0].keeps_frame is True
    assert result.frame_changes[0].splice_pair is None
    assert result.frame_changes[0].run_explains_shift is False
    assert result.reading_frame_holds is True


def test_a_jump_that_keeps_the_frame_past_a_stop_is_other_frame() -> None:
    coding = back_translate(PROTEIN[:CUT]) + "TAACCC" + back_translate(PROTEIN[CUT:])

    result = checked_verdict("CCCC" + coding, PROTEIN[:CUT])

    assert result.verdict == "OTHER_FRAME"
    assert [change.shift for change in result.frame_changes] == [6]
    assert result.frame_changes[0].keeps_frame is True
    assert result.every_change_at_a_splice_pair is False


def test_a_run_copy_that_keeps_the_frame_is_no_miscount() -> None:
    reference = PROTEIN[:CUT] + "DDDD" + PROTEIN[CUT:]
    coding = (
        back_translate(PROTEIN[:CUT])
        + "GAT" * 5
        + "TAA"
        + back_translate(PROTEIN[CUT:])
    )

    result = checked_verdict("CCCC" + coding, PROTEIN[:CUT] + "DDDD", reference)

    change = result.frame_changes[0]
    assert change.keeps_frame is True
    assert change.run is not None
    assert change.run.unit == "GAT"
    assert result.verdict == "OTHER_FRAME"


def test_the_jump_a_frameshift_rests_on_is_listed_past_three_long_jumps() -> None:
    insert = "GCCCCTCCCTCCCTCCCTCCCT"
    coding = (
        back_translate(PROTEIN[:40])
        + insert
        + back_translate(PROTEIN[40:70])
        + insert
        + back_translate(PROTEIN[70:100])
        + insert
        + back_translate(PROTEIN[100:130])
        + "A" * 13
        + back_translate(PROTEIN[130:])
    )

    result = checked_verdict("CCCC" + coding, PROTEIN[:40], slip_reference(130))

    assert result.verdict == "FRAMESHIFT"
    assert [change.shift for change in result.frame_changes] == [1, 22, 22]
    assert [change.shift for change in result.unlisted_changes] == [22]
    assert result.frame_changes[0].run_explains_shift is True


def test_a_jump_past_the_cap_that_is_no_miscount_makes_no_frameshift() -> None:
    insert = "GCCCCTCCCTCCCTCCCTCCCT"
    coding = insert.join(
        back_translate(part)
        for part in (
            PROTEIN[:40],
            PROTEIN[40:70],
            PROTEIN[70:100],
            PROTEIN[100:130],
            PROTEIN[130:],
        )
    )

    result = checked_verdict("CCCC" + coding, PROTEIN[:40])

    assert result.verdict == "OTHER_FRAME"
    assert len(result.frame_changes) + len(result.unlisted_changes) == 4


@pytest.mark.parametrize("at", [85, 100])
def test_a_stop_past_the_near_part_lowers_the_certainty_and_is_stated(at: int) -> None:
    coding = back_translate(PROTEIN)
    edited = coding[: 3 * at] + "TAA" + coding[3 * at + 3 :]

    result = checked_verdict("CCCC" + edited, PROTEIN[:60])

    assert result.verdict == "GENOME_ENCODES"
    assert result.part_open is False
    assert result.part_stop == START + 4 + 3 * at
    assert result.reading_frame_holds is False


def test_a_slip_with_one_window_after_it_does_not_read_as_open() -> None:
    coding = back_translate(PROTEIN[:180]) + "G" + back_translate(PROTEIN[180:])

    result = checked_verdict("CCCC" + coding, PROTEIN[:60])

    assert result.verdict == "GENOME_ENCODES"
    assert result.frame_changes == []
    assert result.part_open is False
    assert result.reading_frame_holds is False


def test_a_last_window_in_another_frame_with_no_stop_is_not_open() -> None:
    reference = PROTEIN[:160] + "GA" * 10
    coding = back_translate(PROTEIN[:160]) + "G" + back_translate("GA" * 10)

    result = checked_verdict("CCCC" + coding, PROTEIN[:60], reference)

    assert result.verdict == "GENOME_ENCODES"
    assert result.frame_changes == []
    assert result.part_stop is None
    assert result.part_open is False


def test_a_part_with_no_model_beside_it_is_not_open() -> None:
    result = checked_verdict("CCCC" + back_translate(PROTEIN), "W" * 40)

    assert result.part_open is False
    assert result.part_stop is None


def test_a_stop_before_the_model_is_read_in_the_model_frame() -> None:
    dna = "CCCC" + back_translate(PROTEIN[:100]) + "G" + back_translate(PROTEIN[100:])
    model_at = dna.index(back_translate(PROTEIN[120:]))

    result = checked_verdict(dna, PROTEIN[120:])

    assert result.part_stop is not None
    at = result.part_stop - START
    assert (at - model_at) % 3 == 0
    assert translate(dna[at : at + 3], STANDARD) == "*"


def test_a_part_open_across_every_window_holds() -> None:
    result = checked_verdict("CCCC" + back_translate(PROTEIN), PROTEIN[:CUT])

    assert result.part_open is True
    assert result.part_stop is None
    assert result.ns_in_part == 0
    assert result.reading_frame_holds is True


def test_a_part_before_the_model_is_read_in_the_model_frame() -> None:
    coding = back_translate(PROTEIN)
    edited = coding[:30] + "TAA" + coding[33:]

    result = checked_verdict("C" + edited, PROTEIN[120:])

    assert result.part_stop == START + 31
    assert result.part_open is False


def test_a_lone_n_on_one_diagonal_is_stated_and_is_no_assembly() -> None:
    coding = back_translate(PROTEIN)
    edited = coding[:300] + "N" + coding[301:]

    result = checked_verdict("CCCC" + edited, PROTEIN[:CUT])

    assert result.verdict == "GENOME_ENCODES"
    assert result.ns_in_part == 1
    assert result.part_open is False


def test_a_lone_n_in_a_jump_is_assembly() -> None:
    dna, model = cut_by("NGG" + "G")

    assert checked_verdict(dna, model).verdict == "ASSEMBLY"


@pytest.mark.parametrize("gap", [5, 20, 100])
def test_a_real_gap_of_ns_is_assembly(gap: int) -> None:
    dna, model = cut_by("N" * gap)

    assert checked_verdict(dna, model).verdict == "ASSEMBLY"


def test_a_group_of_one_window_is_dropped() -> None:
    bases = [0, 30, 61, 90, 120]
    track = SegmentTrack(
        states=["model"] * len(bases),
        hits=[WindowHit(base=base, identity=1.0, in_model=1.0) for base in bases],
    )

    groups = frameshift._blocks(track)

    assert [[residue for residue, _ in group] for group in groups] == [
        [0, 10],
        [30, 40],
    ]


def test_a_repeat_whose_unit_cannot_explain_the_shift_is_not_named() -> None:
    assert repeat_at("TTAC" + "GGC" * 7 + "TTAC", 10, 12, 1) is None
    assert repeat_at("TTAC" + "GGC" * 7 + "TTAC", 10, 12, 3) == ("CGG", 3, 25)


def test_n_is_not_a_repeated_base() -> None:
    assert repeat_at("TCTC" + "N" * 12 + "CTCT", 6, 10, 1) is None
    assert repeat_at("TCTC" + "NC" * 6 + "TCTC", 6, 10, 2) is None


def test_a_run_of_six_bases_is_named_and_of_five_is_not() -> None:
    assert repeat_at("CTCTC" + "A" * 6 + "CTCTC", 7, 7, 1) == ("A", 5, 11)
    assert repeat_at("CTCTC" + "A" * 5 + "CTCTC", 7, 7, 1) is None


def test_a_run_counts_only_when_it_touches_the_span() -> None:
    dna = "CTCTC" + "A" * 6 + "CGTCGACCTG"

    assert repeat_at(dna, 11, 13, 1) is None
    assert repeat_at(dna, 10, 13, 1) == ("A", 5, 11)
    assert repeat_at(dna, 2, 5, 1) == ("A", 5, 11)
    assert repeat_at(dna, 2, 4, 1) is None


def test_a_tandem_repeat_needs_three_copies() -> None:
    assert repeat_at("CTGA" + "GATTAC" * 2 + "CCTGACG", 6, 8, 6) is None
    assert repeat_at("CTGA" + "GATTAC" * 3 + "CCTGACG", 6, 8, 6) is not None


def test_a_homopolymer_explains_one_or_two_bases_and_no_more() -> None:
    dna = "CTCTC" + "A" * 8 + "CTCTC"

    assert repeat_at(dna, 7, 7, 2) == ("A", 5, 13)
    assert repeat_at(dna, 7, 7, 4) is None


def test_two_model_parts_are_a_split_whatever_their_frames() -> None:
    dna, _ = cut_by("G")

    result = check_length(
        PROTEIN, [PROTEIN[:CUT], PROTEIN[CUT:]], window(dna), STANDARD
    )

    assert result.verdict == "SPLIT_CONFIRMED"
    assert result.frame_changes == []


def checked(verdict: str, changes: list[FrameChange]) -> LengthCheck:
    return LengthCheck.model_validate(
        {
            "verdict": verdict,
            "windows": 1,
            "counts": {},
            "track": "M",
            "ns_in_window": 0,
            "at_contig_edge": False,
            "part_open": True,
            "frame_changes": changes,
        }
    )


def test_a_frameshift_verdict_names_its_change() -> None:
    with pytest.raises(ValueError, match="names its frame change"):
        checked("FRAMESHIFT", [])


def test_a_frameshift_verdict_rests_on_a_listed_run() -> None:
    run = RepeatRun(unit="A", bases=13, start=10, end=22)

    with pytest.raises(ValueError, match="names its frame change"):
        checked("FRAMESHIFT", [constructed_change()])
    assert len(checked("FRAMESHIFT", [constructed_change(run=run)]).frame_changes) == 1


@pytest.mark.parametrize(
    ("fields", "fits"),
    [
        ({}, True),
        ({"shift": 3}, False),
        ({"run": None}, False),
        ({"splice_pair": SplicePair(motif="GT..AG", donor=10, acceptor=40)}, False),
        ({"steps_between": 3}, True),
        ({"steps_between": 4}, False),
    ],
)
def test_run_explains_shift_needs_a_frame_change_a_run_no_pair_and_close_parts(
    fields: dict[str, object], fits: bool
) -> None:
    run = RepeatRun(unit="A", bases=13, start=10, end=22)

    assert constructed_change(**{"run": run, **fields}).run_explains_shift is fits


def test_any_read_verdict_can_state_its_changes() -> None:
    assert len(checked("GENOME_ENCODES", [constructed_change()]).frame_changes) == 1
    assert len(checked("ASSEMBLY", [constructed_change()]).frame_changes) == 1


PAIR = SplicePair(motif="GT..AG", donor=10, acceptor=40)


def test_every_change_at_a_splice_pair_needs_a_change_and_a_pair_at_each() -> None:
    paired = constructed_change(splice_pair=PAIR)
    bare = constructed_change()

    assert (
        checked("OTHER_FRAME", [paired, paired]).every_change_at_a_splice_pair is True
    )
    assert checked("OTHER_FRAME", [paired, bare]).every_change_at_a_splice_pair is False
    assert checked("OTHER_FRAME", [bare]).every_change_at_a_splice_pair is False
    assert checked("OTHER_FRAME", []).every_change_at_a_splice_pair is False


def test_a_pair_is_read_over_the_jumps_past_the_cap() -> None:
    paired = constructed_change(splice_pair=PAIR)
    check = checked("OTHER_FRAME", [paired]).model_copy(
        update={"unlisted_changes": [constructed_change()]}
    )

    assert check.every_change_at_a_splice_pair is False


def test_a_jump_keeps_the_frame_when_its_shift_is_a_multiple_of_three() -> None:
    assert constructed_change(shift=-60).keeps_frame is True
    assert constructed_change(shift=3).keeps_frame is True
    assert constructed_change(shift=1).keeps_frame is False
    assert constructed_change(shift=-1).keeps_frame is False


def test_keeps_frame_is_on_the_wire() -> None:
    assert constructed_change(shift=3).model_dump(by_alias=True)["keepsFrame"] is True


def test_the_reading_frame_holds_only_with_no_pair_and_no_frame_change() -> None:
    kept = constructed_change(shift=3)
    kept_at_a_pair = constructed_change(shift=108, splice_pair=PAIR)
    shifted = constructed_change(shift=1)

    assert checked("GENOME_ENCODES", []).reading_frame_holds is True
    assert (
        checked("GENOME_ENCODES", [])
        .model_copy(update={"part_open": False})
        .reading_frame_holds
        is False
    )
    assert checked("GENOME_ENCODES", [kept]).reading_frame_holds is True
    assert checked("GENOME_ENCODES", [kept_at_a_pair]).reading_frame_holds is False
    assert checked("GENOME_ENCODES", [kept, shifted]).reading_frame_holds is False
    assert (
        checked("GENOME_ENCODES", [kept])
        .model_copy(update={"unlisted_changes": [shifted]})
        .reading_frame_holds
        is False
    )


def test_other_frame_holds_its_changes_or_none() -> None:
    assert checked("OTHER_FRAME", []).frame_changes == []
    assert len(checked("OTHER_FRAME", [constructed_change()]).frame_changes) == 1


def test_a_check_holds_a_bounded_number_of_changes() -> None:
    with pytest.raises(ValueError, match="at most 3"):
        checked("FRAMESHIFT", [constructed_change()] * 4)


def test_the_gene_strand_base_turns_a_genome_position_back() -> None:
    plus = window("ACGTACGT")
    minus = window("ACGTACGT", strand="-")

    assert plus.gene_strand_base(plus.genome_position(2)) == 2
    assert minus.gene_strand_base(minus.genome_position(2)) == 2
    assert minus.genome_position(0) == START + 7
    assert minus.gene_strand_base(START) == 7


LEFT = "TTCCGGTTCCTAGCA"
RIGHT = "CCTTGGACACGTTGC"


def test_the_same_run_is_counted_between_its_flanks() -> None:
    strain = LEFT + "A" * 29 + RIGHT
    reference = "G" + LEFT + "A" * 28 + RIGHT + "G"

    assert flanked_span(strain, 15, 44, reference) == (16, 44)


def test_a_repeated_flank_widens_until_it_is_in_one_place() -> None:
    outer = "GCGTACGATCGATTGACTCG"
    strain = outer + LEFT + "A" * 29 + RIGHT + "TGACCATCGGATACGCTTAG"
    decoy = LEFT + "A" * 4 + RIGHT
    reference = decoy + "C" + outer + LEFT + "A" * 28 + RIGHT + "TGACCATCGGATACGCTTAG"
    begin = len(decoy) + 1 + len(outer) + 15

    assert flanked_span(strain, 35, 64, reference) == (begin, begin + 28)


def test_a_flank_that_stays_repeated_gives_no_comparison() -> None:
    unit = "TTCCGG"
    strain = unit * 30 + "A" * 29 + RIGHT * 10
    reference = unit * 40 + "A" * 28 + RIGHT * 10

    assert flanked_span(strain, 180, 209, reference) == "FLANK_REPEATED"


def test_a_flank_at_a_contig_end_is_too_short() -> None:
    strain = "TTCC" + "A" * 29 + RIGHT

    assert flanked_span(strain, 4, 33, "G" + strain) == "FLANK_SHORT"
    assert flanked_span(LEFT + "A" * 29 + "TT", 15, 44, LEFT + "A" * 28 + "TT") == (
        "FLANK_SHORT"
    )


def test_a_flank_the_reference_lacks_gives_no_comparison() -> None:
    strain = LEFT + "A" * 29 + RIGHT

    assert flanked_span(strain, 15, 44, "G" * 90) == "FLANK_MISSING"
    assert flanked_span(strain, 15, 44, RIGHT + "A" * 28 + LEFT) == "FLANK_MISSING"


def test_flanks_with_nothing_between_them_give_no_comparison() -> None:
    strain = LEFT + "A" * 29 + RIGHT

    assert flanked_span(strain, 15, 44, LEFT + RIGHT) == "EMPTY_SPAN"


def constructed_reference(bases: int) -> ReferenceRun:
    return ReferenceRun(
        gene="constructed_gene",
        source=SOURCE,
        strand="+",
        start=1,
        end=bases,
        bases=bases,
    )


def constructed_calls() -> VariantCalls:
    return VariantCalls(
        site="constructed_site",
        organism="constructed organism",
        seqid="constructed_seq",
        start=1,
        end=2,
        sites=[],
        samples=[],
        homopolymer_bases=None,
    )


def test_a_change_carries_a_comparison_or_the_reason_for_none() -> None:
    with pytest.raises(ValueError, match="reference run or the reason"):
        constructed_change(
            reference_run=constructed_reference(2), reference_unread="FLANK_MISSING"
        )


def test_a_change_carries_variant_calls_or_the_reason_for_none() -> None:
    with pytest.raises(ValueError, match="variant calls or the reason"):
        constructed_change(
            variant_calls=constructed_calls(), variants_unread="TOO_MANY_VARIANTS"
        )


def test_the_two_counts_are_compared_with_the_shift() -> None:
    run = RepeatRun(unit="A", bases=29, start=1, end=29)

    assert (
        constructed_change(
            run=run, reference_run=constructed_reference(28)
        ).counts_match_shift
        is True
    )
    assert (
        constructed_change(
            run=run, reference_run=constructed_reference(27)
        ).counts_match_shift
        is False
    )
    assert (
        constructed_change(
            run=run, reference_run=constructed_reference(29)
        ).counts_match_shift
        is False
    )
    assert constructed_change(run=run).counts_match_shift is None
    assert (
        constructed_change(reference_run=constructed_reference(29)).counts_match_shift
        is None
    )


def test_a_count_on_the_other_side_of_the_shift_does_not_match() -> None:
    run = RepeatRun(unit="A", bases=29, start=1, end=29)
    change = constructed_change(run=run, reference_run=constructed_reference(30))

    assert change.counts_match_shift is False


def test_a_shift_of_minus_one_matches_one_base_fewer() -> None:
    run = RepeatRun(unit="A", bases=27, start=1, end=27)
    change = constructed_change(
        run=run, shift=-1, reference_run=constructed_reference(28)
    )

    assert change.counts_match_shift is True

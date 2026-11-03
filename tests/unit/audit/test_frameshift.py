import pytest
from tests._support.nf54_frameshift import (
    MODEL_PROTEIN,
    REFERENCE_PROTEIN,
    model_coding,
    run_offset,
)
from tests._support.proteins import PROTEIN, back_translate

from veupathdb_mcp.audit.codes import GeneticCode, reverse_complement
from veupathdb_mcp.audit.frameshift import Frameshift, RepeatRun, reference_span
from veupathdb_mcp.audit.length import LengthCheck, check_length
from veupathdb_mcp.audit.windows import DnaWindow, GenomeSource, confirm_in_dna

STANDARD = GeneticCode.STANDARD
SOURCE = GenomeSource(site="plasmodb", organism="pfalNF54", seqid="chr4")
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


def cut_by_one_base(insert: str) -> tuple[str, str]:
    dna = back_translate(PROTEIN[:CUT]) + insert + back_translate(PROTEIN[CUT:])
    return "CCCC" + dna + "CCCC", PROTEIN[:CUT]


def test_each_located_window_records_its_frame() -> None:
    dna = "C" + back_translate(PROTEIN[:60]) + "GG" + back_translate(PROTEIN[60:])

    track = confirm_in_dna(PROTEIN, [PROTEIN[:60]], dna, "+", STANDARD)

    assert track.states[:5] == ["model"] * 5
    assert track.states[6:] == ["genome_same_strand"] * 13
    assert track.frames[:5] == [1] * 5
    assert track.frames[7:] == [0] * 12


def test_a_window_on_the_other_strand_records_no_frame() -> None:
    dna = reverse_complement(back_translate(PROTEIN))

    track = confirm_in_dna(PROTEIN, [PROTEIN[:30]], dna, "+", STANDARD)

    assert track.counts == {"model": 2, "genome_other_strand": 17}
    assert track.frames == [None] * 19


def test_a_one_base_insertion_in_a_poly_a_run_is_a_frameshift_at_that_run() -> None:
    coding = model_coding()
    dna = "CC" + coding

    result = check_length(REFERENCE_PROTEIN, [MODEL_PROTEIN], window(dna), STANDARD)

    assert result.verdict == "FRAMESHIFT"
    [shift] = result.frameshifts
    first = START + 2 + run_offset(coding)
    assert shift.run == RepeatRun(unit="A", bases=29, start=first, end=first + 28)
    assert shift.shift == 1
    assert shift.source == SOURCE
    assert first <= shift.start <= shift.end <= first + 40
    assert shift.frame_before != shift.frame_after


def test_a_minus_strand_gene_names_its_run_on_the_genome() -> None:
    coding = model_coding()
    dna = reverse_complement("CC" + coding)

    result = check_length(
        REFERENCE_PROTEIN, [MODEL_PROTEIN], window(dna, strand="-"), STANDARD
    )

    assert result.verdict == "FRAMESHIFT"
    [shift] = result.frameshifts
    run = shift.run
    assert run is not None
    assert (run.unit, run.bases) == ("A", 29)
    assert dna[run.start - START : run.end - START + 1] == "T" * 29


def test_a_clean_truncation_with_no_frame_change_stays_genome_encodes() -> None:
    dna = "CCCC" + back_translate(PROTEIN) + "CCCC"

    result = check_length(PROTEIN, [PROTEIN[:CUT]], window(dna), STANDARD)

    assert result.verdict == "GENOME_ENCODES"
    assert result.frameshifts == []


def test_a_missing_part_past_an_intron_stays_genome_encodes() -> None:
    dna = (
        "CCCC"
        + back_translate(PROTEIN[:CUT])
        + "G" * 100
        + back_translate(PROTEIN[CUT:])
    )

    result = check_length(PROTEIN, [PROTEIN[:CUT]], window(dna), STANDARD)

    assert result.verdict == "GENOME_ENCODES"
    assert result.frameshifts == []


def test_a_frame_change_the_model_spans_is_not_a_frameshift() -> None:
    dna, _ = cut_by_one_base("GTTG")
    model = PROTEIN[:150]

    result = check_length(PROTEIN, [model], window(dna), STANDARD)

    assert result.verdict == "GENOME_ENCODES"
    assert result.frameshifts == []


def test_a_deleted_base_reads_as_a_negative_shift() -> None:
    coding = back_translate(PROTEIN)
    at = 3 * CUT
    dna = "CCCC" + coding[:at] + coding[at + 1 :]

    result = check_length(PROTEIN, [PROTEIN[:CUT]], window(dna), STANDARD)

    assert result.verdict == "FRAMESHIFT"
    assert [shift.shift for shift in result.frameshifts] == [-1]


def test_a_frame_change_outside_any_run_names_no_run() -> None:
    dna, model = cut_by_one_base("G")

    result = check_length(PROTEIN, [model], window(dna), STANDARD)

    assert result.verdict == "FRAMESHIFT"
    assert [shift.run for shift in result.frameshifts] == [None]


def test_a_tandem_repeat_is_named_when_no_homopolymer_holds_the_change() -> None:
    dna, model = cut_by_one_base("GTGTGTGTGTG")

    result = check_length(PROTEIN, [model], window(dna), STANDARD)

    assert result.verdict == "FRAMESHIFT"
    [shift] = result.frameshifts
    assert shift.run is not None
    assert (shift.run.unit, shift.run.bases) in {("GT", 11), ("TG", 11)}


def test_two_model_parts_are_a_split_whatever_their_frames() -> None:
    dna, _ = cut_by_one_base("G")

    result = check_length(
        PROTEIN, [PROTEIN[:CUT], PROTEIN[CUT:]], window(dna), STANDARD
    )

    assert result.verdict == "SPLIT_CONFIRMED"
    assert result.frameshifts == []


def test_a_frameshift_verdict_names_its_frameshifts() -> None:
    with pytest.raises(ValueError, match="names its frameshifts"):
        LengthCheck(
            verdict="FRAMESHIFT",
            windows=1,
            counts={},
            track="M",
            ns_in_window=0,
            at_contig_edge=False,
        )


def test_another_verdict_names_no_frameshift() -> None:
    shift = Frameshift(
        source=SOURCE,
        strand="+",
        start=10,
        end=12,
        frame_before=0,
        frame_after=1,
        shift=1,
        reference_residues=(5, 6),
        run=None,
    )

    with pytest.raises(ValueError, match="names its frameshifts"):
        LengthCheck(
            verdict="GENOME_ENCODES",
            windows=1,
            counts={},
            track="M",
            ns_in_window=0,
            at_contig_edge=False,
            frameshifts=[shift],
        )


def test_the_same_run_is_counted_between_its_flanks_in_the_reference() -> None:
    assert reference_span("TTCCGG" + "A" * 28 + "CCTTGG", "TTCCGG", "CCTTGG") == (6, 34)


def test_a_reference_without_both_flanks_holds_no_span() -> None:
    assert reference_span("TTCCGG" + "A" * 28, "TTCCGG", "CCTTGG") is None


def test_the_nearest_right_flank_closes_a_repeated_left_flank() -> None:
    dna = "TTCCGG" + "A" * 400 + "TTCCGG" + "A" * 5 + "CCTTGG"

    assert reference_span(dna, "TTCCGG", "CCTTGG") == (412, 417)

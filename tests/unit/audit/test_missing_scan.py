import pytest
from pydantic import ValidationError
from tests._support.missing_site import tga_for_w
from tests._support.proteins import PROTEIN, back_translate

from veupathdb_mcp.audit.codes import GeneticCode, reverse_complement
from veupathdb_mcp.audit.missing import locate_protein, scan_for_protein

CODE = GeneticCode.STANDARD
FILLER = "C" * 3000
TAIL = PROTEIN + "KLVDAEFGH"


def gene_dna(coding: str) -> str:
    return FILLER + "TAA" + coding + "TAA" + FILLER


def test_a_protein_on_the_minus_strand_is_located_with_its_span() -> None:
    coding = back_translate(PROTEIN)
    window = FILLER + reverse_complement(coding) + FILLER

    located = locate_protein(PROTEIN, window, 50001, CODE)

    assert (located.windows, located.found, located.share) == (19, 19, 1.0)
    assert located.span == (53001, 53600)
    assert located.ns == 0


def test_a_protein_on_the_plus_strand_is_located_with_its_span() -> None:
    window = FILLER + "A" + back_translate(PROTEIN) + FILLER

    located = locate_protein(PROTEIN, window, 1, CODE)

    assert (located.found, located.span) == (19, (3002, 3601))


def test_a_protein_absent_from_the_window_has_no_span() -> None:
    located = locate_protein(PROTEIN, FILLER + "NNNnn" + FILLER, 1, CODE)

    assert (located.found, located.share, located.span, located.ns) == (
        0,
        0.0,
        None,
        5,
    )


def test_a_window_half_inside_the_encoded_part_is_found() -> None:
    window = FILLER + back_translate(PROTEIN[:100]) + FILLER

    located = locate_protein(PROTEIN, window, 1, CODE)

    assert (located.windows, located.found, located.share) == (19, 10, 0.526)
    assert located.span == (3001, 3330)


def test_a_protein_shorter_than_a_window_is_refused() -> None:
    with pytest.raises(ValidationError, match="windows"):
        locate_protein(PROTEIN[:19], back_translate(PROTEIN), 1, CODE)


def test_an_intact_gene_is_one_open_frame_with_no_stop() -> None:
    window = reverse_complement(gene_dna(back_translate(PROTEIN)))

    scan = scan_for_protein(PROTEIN, window, 1, CODE)

    assert scan.located.span == (3004, 3603)
    assert scan.open_frame is not None
    assert (scan.open_frame.length, scan.open_frame.identical) == (200, 200)
    assert (scan.stops, scan.intact_frame) == ([], True)


def test_the_open_frame_runs_past_the_last_window_to_its_stop() -> None:
    scan = scan_for_protein(TAIL, gene_dna(back_translate(TAIL)), 1, CODE)

    assert (scan.located.windows, scan.located.span) == (19, (3004, 3603))
    assert scan.open_frame is not None
    assert (scan.open_frame.length, scan.open_frame.identical) == (209, 209)
    assert (scan.stops, scan.intact_frame) == ([], True)


def test_the_open_frame_runs_to_the_window_end_without_a_stop() -> None:
    window = FILLER + "TAA" + back_translate(PROTEIN) + "CC"

    scan = scan_for_protein(PROTEIN, window, 1, CODE)

    assert scan.open_frame is not None
    assert (scan.open_frame.length, scan.open_frame.identical) == (200, 200)


def test_an_in_frame_stop_is_named_by_its_residue() -> None:
    coding = back_translate(PROTEIN[:120]) + "TAA" + back_translate(PROTEIN[121:])

    scan = scan_for_protein(PROTEIN, gene_dna(coding), 1, CODE)

    assert scan.located.found == 19
    assert scan.open_frame is not None
    assert (scan.open_frame.length, scan.open_frame.identical) == (120, 120)
    assert (scan.stops, scan.intact_frame) == ([121], False)


def test_a_frame_shift_is_not_an_intact_frame() -> None:
    coding = back_translate(PROTEIN[:100]) + "A" + back_translate(PROTEIN[100:])

    scan = scan_for_protein(PROTEIN, gene_dna(coding), 1, CODE)

    assert scan.located.found == 19
    assert (scan.stops, scan.intact_frame) == ([103, 110], False)


def test_an_intron_stop_inside_the_covered_stretch_is_listed() -> None:
    intron = "GTAAGT" + "A" * 81 + "TAG"
    coding = back_translate(PROTEIN[:100]) + intron + back_translate(PROTEIN[100:])

    scan = scan_for_protein(PROTEIN, gene_dna(coding), 1, CODE)

    assert scan.located.found == 19
    assert (scan.stops, scan.intact_frame) == ([100], False)


def test_the_code_decides_whether_tga_is_a_stop() -> None:
    dna = gene_dna(tga_for_w(PROTEIN))

    standard = scan_for_protein(PROTEIN, dna, 1, CODE)
    tryptophan = scan_for_protein(PROTEIN, dna, 1, GeneticCode.UGA_TRYPTOPHAN)

    assert standard.intact_frame is False
    assert len(standard.stops) == PROTEIN.count("W")
    assert tryptophan.open_frame is not None
    assert (tryptophan.open_frame.length, tryptophan.open_frame.identical) == (
        200,
        200,
    )
    assert (tryptophan.stops, tryptophan.intact_frame) == ([], True)


def test_a_scan_without_a_span_reads_no_frame() -> None:
    scan = scan_for_protein(PROTEIN, FILLER, 1, CODE)

    assert (scan.located.span, scan.open_frame) == (None, None)
    assert (scan.stops, scan.intact_frame) == ([], None)

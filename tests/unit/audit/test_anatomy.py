import random
import re
from collections.abc import Iterator

import pydantic
import pytest

from veupathdb_mcp.audit.anatomy import (
    RUN_PATTERN,
    Junction,
    ModelAnatomy,
    pseudogene_anatomy,
)

START = 1000
CG = "CG" * 60
AFTER = 1100
BEFORE = 1161


def test_a_one_base_gap_inside_a_run_of_nine_a_gives_gap_1_mod_1_and_run_a_9() -> None:
    window = CG + "A" * 9 + CG
    run_start = START + len(CG)

    anatomy = pseudogene_anatomy(
        [(START + 10, run_start + 3), (run_start + 5, run_start + 40)],
        window,
        START,
        50000,
    )

    [junction] = anatomy.junctions
    assert (junction.after, junction.before) == (run_start + 3, run_start + 5)
    assert (junction.gap, junction.gap_mod_3) == (1, 1)
    assert (junction.run_base, junction.run_length) == ("A", 9)
    assert junction.ns_within_100 == 0


def test_a_gap_of_120_bases_gives_mod_0_and_the_run_at_its_first_base() -> None:
    gap = "TTTTTTT" + "CG" * 56 + "A"
    window = CG + gap + CG
    first_end = START + len(CG) - 1

    anatomy = pseudogene_anatomy(
        [(START, first_end), (first_end + 121, first_end + 160)],
        window,
        START,
        50000,
    )

    [junction] = anatomy.junctions
    assert (junction.gap, junction.gap_mod_3) == (120, 0)
    assert (junction.run_base, junction.run_length) == ("T", 7)


def test_a_run_ten_bases_inside_a_gap_of_120_gives_the_run_at_the_gap_end() -> None:
    gap = "CG" * 5 + "T" * 9 + "CG" * 50 + "C"
    window = CG + gap + CG
    first_end = START + len(CG) - 1

    anatomy = pseudogene_anatomy(
        [(START, first_end), (first_end + 121, first_end + 160)],
        window,
        START,
        50000,
    )

    [junction] = anatomy.junctions
    assert (junction.run_base, junction.run_length) == ("C", 2)


def run_of_eight_g_at(start: int) -> str:
    window = list("AC" * 200)
    window[start - START : start - START + 8] = "G" * 8
    return "".join(window)


@pytest.mark.parametrize(
    ("run_start", "run_length"),
    [
        (AFTER + 1 - 5 - 7, 8),
        (AFTER + 1 - 6 - 7, 1),
        (AFTER + 1 + 5, 8),
        (AFTER + 1 + 6, 1),
        (BEFORE - 1 - 5 - 7, 8),
        (BEFORE - 1 - 6 - 7, 1),
        (BEFORE - 1 + 5, 8),
        (BEFORE - 1 + 6, 1),
    ],
)
def test_a_run_counts_when_a_base_of_it_lies_within_5_of_a_gap_end(
    run_start: int, run_length: int
) -> None:
    anatomy = pseudogene_anatomy(
        [(START + 1, AFTER), (BEFORE, START + 300)],
        run_of_eight_g_at(run_start),
        START,
        50000,
    )

    [junction] = anatomy.junctions
    assert junction.gap == 60
    assert junction.run_length == run_length
    assert junction.run_base == ("G" if run_length == 8 else "A")


def test_a_single_segment_has_no_junctions() -> None:
    anatomy = pseudogene_anatomy([(START + 5, START + 99)], CG, START, 50000)

    assert anatomy.junctions == []
    assert anatomy.segments == [(START + 5, START + 99)]


def test_ns_within_100_bases_of_a_junction_are_counted() -> None:
    window = "CG" * 100 + "N" * 10 + "CG" * 30 + "A" + "CG" * 30 + "N" * 7 + "CG" * 100
    gap_at = START + 200 + 10 + 60

    anatomy = pseudogene_anatomy(
        [(START, gap_at - 1), (gap_at + 1, START + len(window) - 1)],
        window,
        START,
        50000,
    )

    [junction] = anatomy.junctions
    assert junction.ns_within_100 == 17
    assert anatomy.ns_in_gene == 17


@pytest.mark.parametrize(("offset", "counted"), [(100, 1), (101, 0)])
def test_an_n_counts_when_it_lies_within_100_of_a_gap_end(
    offset: int, counted: int
) -> None:
    window = list("AC" * 200)
    window[AFTER + 1 - offset - START] = "N"
    window[BEFORE - 1 + offset - START] = "N"

    anatomy = pseudogene_anatomy(
        [(START, AFTER), (BEFORE, START + 399)], "".join(window), START, 50000
    )

    [junction] = anatomy.junctions
    assert junction.ns_within_100 == 2 * counted


def test_ns_further_than_100_bases_from_a_junction_are_not_counted() -> None:
    window = "N" * 4 + "CG" * 60 + "A" + "CG" * 60 + "N" * 4
    gap_at = START + 4 + 120

    anatomy = pseudogene_anatomy(
        [(START + 4, gap_at - 1), (gap_at + 1, gap_at + 120)], window, START, 50000
    )

    [junction] = anatomy.junctions
    assert junction.ns_within_100 == 0
    assert anatomy.ns_in_gene == 0


def test_the_contig_distances_are_measured_from_the_first_and_last_segment() -> None:
    window = "CG" * 200

    anatomy = pseudogene_anatomy(
        [(START + 250, START + 300), (START + 20, START + 100)], window, START, 1500
    )

    assert anatomy.segments == [(START + 20, START + 100), (START + 250, START + 300)]
    assert anatomy.to_contig_start == START + 19
    assert anatomy.to_contig_end == 1500 - (START + 300)


class CountedPattern:
    def __init__(self, pattern: re.Pattern[str]) -> None:
        self.pattern = pattern
        self.scanned: list[int] = []

    def finditer(self, text: str) -> Iterator[re.Match[str]]:
        self.scanned.append(len(text))
        return self.pattern.finditer(text)


def test_199_junctions_on_a_250000_base_window_scan_the_window_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bases = random.Random(12)
    window = "".join(bases.choice("ACGT") for _ in range(250000))
    segments = [(START + 1000 * i, START + 1000 * i + 499) for i in range(200)]
    runs = CountedPattern(RUN_PATTERN)
    monkeypatch.setattr("veupathdb_mcp.audit.anatomy.RUN_PATTERN", runs)

    anatomy = pseudogene_anatomy(segments, window, START, 300000)

    assert len(anatomy.junctions) == 199
    assert {j.gap for j in anatomy.junctions} == {500}
    assert runs.scanned == [250000]


def test_segments_outside_the_window_are_refused() -> None:
    with pytest.raises(ValueError, match="1000-1239"):
        pseudogene_anatomy([(START + 200, START + 300)], "CG" * 120, START, 50000)


def test_no_segment_is_refused() -> None:
    with pytest.raises(ValueError, match="no segment"):
        pseudogene_anatomy([], CG, START, 50000)


def test_overlapping_segments_are_refused() -> None:
    with pytest.raises(pydantic.ValidationError, match="overlap"):
        pseudogene_anatomy(
            [(START, START + 50), (START + 50, START + 90)], CG, START, 50000
        )


def test_a_junction_gives_its_gap_and_gap_mod_3_from_its_ends() -> None:
    junction = Junction(
        after=10, before=15, run_base="A", run_length=3, ns_within_100=0
    )

    assert junction.model_dump(by_alias=True) == {
        "after": 10,
        "before": 15,
        "gap": 4,
        "gapMod3": 1,
        "runBase": "A",
        "runLength": 3,
        "nsWithin100": 0,
    }


def test_a_junction_whose_ends_do_not_advance_is_refused() -> None:
    with pytest.raises(pydantic.ValidationError, match="overlap"):
        Junction(after=15, before=15, run_base="A", run_length=1, ns_within_100=0)


def junction(after: int, before: int) -> Junction:
    return Junction(
        after=after, before=before, run_base="A", run_length=1, ns_within_100=0
    )


@pytest.mark.parametrize(
    ("segments", "junctions", "refusal"),
    [
        ([(10, 20), (50, 60)], [], "2 segments and 0 junctions"),
        ([(10, 20), (50, 60)], [junction(21, 50)], "junction 21-50"),
        ([(20, 10)], [], "segment 20-10"),
    ],
)
def test_a_model_anatomy_ties_its_junctions_to_its_segments(
    segments: list[tuple[int, int]], junctions: list[Junction], refusal: str
) -> None:
    with pytest.raises(pydantic.ValidationError, match=refusal):
        ModelAnatomy(
            segments=segments,
            junctions=junctions,
            to_contig_start=9,
            to_contig_end=0,
            ns_in_gene=0,
        )

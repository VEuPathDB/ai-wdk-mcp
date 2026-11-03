"""Where the windows of a reference protein change reading frame in a genome window,
and the repeat that holds the change."""

from __future__ import annotations

from itertools import groupby, pairwise

from pydantic import ConfigDict
from veupathdb.model import CamelModel

from veupathdb_mcp.audit.codes import GeneticCode, translate
from veupathdb_mcp.audit.variant_calls import VariantCalls
from veupathdb_mcp.audit.windows import (
    STEP,
    WINDOW,
    DnaWindow,
    GenomeSource,
    SegmentTrack,
    Strand,
    WindowHit,
)

MAX_SHIFT_BASES = 20
MIN_BLOCK_WINDOWS = 2
MAX_GAP_WINDOWS = 3
BOUNDARY_WINDOWS = 2
MIN_RUN_BASES = 6
MAX_REPEAT_UNIT = 6
MIN_REPEAT_COPIES = 3
RUN_REACH = 300
FLANK_BASES = 15
MAX_REFERENCE_SPAN = 300

type _Placed = tuple[int, WindowHit]
type _Block = list[_Placed]
type _Repeat = tuple[str, int, int]


class RepeatRun(CamelModel):
    model_config = ConfigDict(frozen=True)

    unit: str
    bases: int
    start: int
    end: int


class ReferenceRun(CamelModel):
    model_config = ConfigDict(frozen=True)

    gene: str
    source: GenomeSource
    strand: Strand
    start: int
    end: int
    bases: int


class Frameshift(CamelModel):
    model_config = ConfigDict(frozen=True)

    source: GenomeSource
    strand: Strand
    start: int
    end: int
    frame_before: int
    frame_after: int
    shift: int
    reference_residues: tuple[int, int]
    run: RepeatRun | None
    reference_run: ReferenceRun | None = None
    variant_calls: VariantCalls | None = None


def _diagonal(placed: _Placed) -> int:
    residue, hit = placed
    return hit.base - 3 * residue


def _blocks(track: SegmentTrack) -> list[_Block]:
    placed = [(k * STEP, hit) for k, hit in enumerate(track.hits) if hit is not None]
    groups = [list(group) for _, group in groupby(placed, key=_diagonal)]
    return [group for group in groups if len(group) >= MIN_BLOCK_WINDOWS]


def _changes_frame(before: _Block, after: _Block) -> bool:
    shift = _diagonal(after[0]) - _diagonal(before[-1])
    gap = (after[0][0] - before[-1][0]) // STEP
    boundary = (*before[-BOUNDARY_WINDOWS:], *after[:BOUNDARY_WINDOWS])
    return (
        shift % 3 != 0
        and abs(shift) <= MAX_SHIFT_BASES
        and gap <= MAX_GAP_WINDOWS
        and any(hit.beyond_model for _, hit in boundary)
    )


def _breaks(
    reference: str, dna: str, code: GeneticCode, before: _Block, after: _Block
) -> tuple[int, int]:
    first, last = before[-1][0], after[0][0] + WINDOW
    left, right = _diagonal(before[-1]), _diagonal(after[0])

    def reads(diagonal: int, residue: int) -> bool:
        base = diagonal + 3 * residue
        return base >= 0 and translate(dna[base : base + 3], code) == reference[residue]

    scores = {
        cut: sum(reads(left, i) for i in range(first, cut))
        + sum(reads(right, i) for i in range(cut, last))
        for cut in range(first, last + 1)
    }
    top = max(scores.values())
    tied = [cut for cut, score in scores.items() if score == top]
    return min(tied), max(tied)


def _stretches(dna: str, lo: int, hi: int, unit: int) -> list[tuple[int, int]]:
    stop = min(len(dna), hi + RUN_REACH)
    least = max(MIN_RUN_BASES, MIN_REPEAT_COPIES * unit)
    found: list[tuple[int, int]] = []
    at = max(0, lo - RUN_REACH)
    while at + unit < stop:
        if dna[at] != dna[at + unit]:
            at += 1
            continue
        end = at
        while end + unit < stop and dna[end] == dna[end + unit]:
            end += 1
        if end + unit > lo and at <= hi and end + unit - at >= least:
            found.append((at, end + unit))
        at = end + 1
    return found


def repeat_at(dna: str, lo: int, hi: int) -> _Repeat | None:
    for units in ((1,), tuple(range(2, MAX_REPEAT_UNIT + 1))):
        found = [
            (end - start, -unit, -start, unit)
            for unit in units
            for start, end in _stretches(dna, lo, hi, unit)
        ]
        if found:
            bases, _, negative_start, unit = max(found)
            start = -negative_start
            return dna[start : start + unit], start, start + bases
    return None


def _genome_run(window: DnaWindow, repeat: _Repeat) -> RepeatRun:
    unit, start, end = repeat
    ends = sorted((window.genome_position(start), window.genome_position(end - 1)))
    return RepeatRun(unit=unit, bases=end - start, start=ends[0], end=ends[1])


def _frameshift(
    reference: str, window: DnaWindow, code: GeneticCode, before: _Block, after: _Block
) -> Frameshift:
    dna = window.on_gene_strand
    left, right = _diagonal(before[-1]), _diagonal(after[0])
    first, last = _breaks(reference, dna, code, before, after)
    lo = min(left, right) + 3 * first
    hi = max(left, right) + 3 * last
    ends = sorted((window.genome_position(lo), window.genome_position(hi)))
    repeat = repeat_at(dna, lo, hi)
    return Frameshift(
        source=window.source,
        strand=window.strand,
        start=ends[0],
        end=ends[1],
        frame_before=window.genome_frame(left),
        frame_after=window.genome_frame(right),
        shift=right - left,
        reference_residues=(first + 1, last + 1),
        run=None if repeat is None else _genome_run(window, repeat),
    )


def locate_frameshifts(
    reference: str, track: SegmentTrack, window: DnaWindow, code: GeneticCode
) -> list[Frameshift]:
    return [
        _frameshift(reference, window, code, before, after)
        for before, after in pairwise(_blocks(track))
        if _changes_frame(before, after)
    ]


def flanks_of(window: DnaWindow, shift: Frameshift) -> tuple[str, str]:
    dna = window.on_gene_strand
    first, last = shift.start, shift.end
    if shift.run is not None:
        first, last = shift.run.start, shift.run.end
    low, high = sorted((window.gene_strand_base(first), window.gene_strand_base(last)))
    return (
        dna[max(0, low - FLANK_BASES) : low],
        dna[high + 1 : high + 1 + FLANK_BASES],
    )


def reference_span(dna: str, left: str, right: str) -> tuple[int, int] | None:
    spans: list[tuple[int, int]] = []
    at = dna.find(left)
    while at >= 0:
        start = at + len(left)
        end = dna.find(right, start, start + MAX_REFERENCE_SPAN + len(right))
        if end >= 0:
            spans.append((start, end))
        at = dna.find(left, at + 1)
    return min(spans, key=lambda span: span[1] - span[0], default=None)

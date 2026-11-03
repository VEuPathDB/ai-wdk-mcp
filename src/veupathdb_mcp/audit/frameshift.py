from __future__ import annotations

from itertools import groupby, pairwise
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, model_validator
from veupathdb.model import CamelModel

from veupathdb_mcp.audit.codes import GeneticCode, translate
from veupathdb_mcp.audit.introns import CANONICAL_MOTIFS, MIN_INTRON
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
from veupathdb_mcp.computed import computed

MIN_BLOCK_WINDOWS = 2
MAX_GAP_WINDOWS = 3
BOUNDARY_WINDOWS = 2
MIN_RUN_BASES = 6
MAX_REPEAT_UNIT = 6
MIN_REPEAT_COPIES = 3
MAX_MISCOUNT_UNITS = 2
MAX_FRAME_CHANGES = 3
RUN_REACH = 300
SPLICE_SLACK = 6
MISSES_THAT_END_A_FRAME = 2
FLANK_WIDTHS = (15, 30, 60, 120)
MAX_REFERENCE_SPAN = 300
_GAP = "N"

type _Placed = tuple[int, WindowHit]
type _Block = list[_Placed]
type _Repeat = tuple[str, int, int]
type _EncodedVerdict = Literal["GENOME_ENCODES", "FRAMESHIFT", "OTHER_FRAME"]
type ReferenceMiss = Literal[
    "MODEL_UNREAD",
    "WINDOW_TOO_LONG",
    "FLANK_SHORT",
    "FLANK_MISSING",
    "FLANK_REPEATED",
    "EMPTY_SPAN",
]
type VariantsUnread = Literal[
    "NO_REFERENCE_RUN", "NO_VARIANT_SEARCH", "SEARCH_REFUSED", "TOO_MANY_VARIANTS"
]


class RepeatRun(CamelModel):
    model_config = ConfigDict(frozen=True)

    unit: str
    bases: int
    start: int
    end: int


class SplicePair(CamelModel):
    model_config = ConfigDict(frozen=True)

    motif: str
    donor: int
    acceptor: int


class ReferenceRun(CamelModel):
    model_config = ConfigDict(frozen=True)

    gene: str
    source: GenomeSource
    strand: Strand
    start: int
    end: int
    bases: int


class FrameChange(CamelModel):
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
    splice_pair: SplicePair | None = None
    steps_between: int
    model_goes_on: bool = False
    reference_run: ReferenceRun | None = None
    reference_unread: ReferenceMiss | None = None
    variant_calls: VariantCalls | None = None
    variants_unread: VariantsUnread | None = None

    @model_validator(mode="after")
    def _a_read_or_its_reason(self) -> Self:
        if self.reference_run is not None and self.reference_unread is not None:
            msg = "a frameshift holds a reference run or the reason for none"
            raise ValueError(msg)
        if self.variant_calls is not None and self.variants_unread is not None:
            msg = "a frameshift holds variant calls or the reason for none"
            raise ValueError(msg)
        return self

    @computed
    def keeps_frame(self) -> bool:
        return self.shift % 3 == 0

    @computed
    def run_explains_shift(self) -> bool:
        return (
            not self.keeps_frame
            and self.steps_between <= MAX_GAP_WINDOWS
            and self.run is not None
            and self.splice_pair is None
        )

    @computed
    def counts_match_shift(self) -> bool | None:
        if self.run is None or self.reference_run is None:
            return None
        return self.run.bases - self.reference_run.bases == self.shift


def _diagonal(placed: _Placed) -> int:
    residue, hit = placed
    return hit.base - 3 * residue


def _blocks(track: SegmentTrack) -> list[_Block]:
    placed = [(k * STEP, hit) for k, hit in enumerate(track.hits) if hit is not None]
    groups = [list(group) for _, group in groupby(placed, key=_diagonal)]
    return [group for group in groups if len(group) >= MIN_BLOCK_WINDOWS]


def _shift(before: _Block, after: _Block) -> int:
    return _diagonal(after[0]) - _diagonal(before[-1])


def _held(block: list[_Placed]) -> bool:
    return any(not hit.beyond_model for _, hit in block)


def _is_change(before: _Block, after: _Block) -> bool:
    boundary = (*before[-BOUNDARY_WINDOWS:], *after[:BOUNDARY_WINDOWS])
    return _shift(before, after) != 0 and any(hit.beyond_model for _, hit in boundary)


class _Span(BaseModel):
    model_config = ConfigDict(frozen=True)

    first_cut: int
    last_cut: int
    lo: int
    hi: int
    left_end: int
    right_start: int


def _span(
    reference: str, dna: str, code: GeneticCode, before: _Block, after: _Block
) -> _Span:
    first, last = before[-1][0], after[0][0] + WINDOW
    left, right = _diagonal(before[-1]), _diagonal(after[0])

    def reads(diagonal: int, residue: int) -> bool:
        base = diagonal + 3 * residue
        return (
            0 <= residue < len(reference)
            and base >= 0
            and translate(dna[base : base + 3], code) == reference[residue]
        )

    scores = {
        cut: sum(reads(left, i) for i in range(first, cut))
        + sum(reads(right, i) for i in range(cut, last))
        for cut in range(first, last + 1)
    }

    def reach(diagonal: int, residues: range) -> int:
        held = residues[0]
        missed = 0
        for residue in residues:
            missed = 0 if reads(diagonal, residue) else missed + 1
            if missed == MISSES_THAT_END_A_FRAME:
                break
            if missed == 0:
                held = residue
        return held

    left_end = reach(left, range(first, last))
    right_start = reach(right, range(last - 1, first - 1, -1))
    top = max(scores.values())
    tied = [cut for cut, score in scores.items() if score == top]
    return _Span(
        first_cut=min(tied),
        last_cut=max(tied),
        lo=max(0, min(left, right) + 3 * min(tied)),
        hi=min(len(dna) - 1, max(left, right) + 3 * max(tied)),
        left_end=left + 3 * (left_end + 1),
        right_start=right + 3 * right_start,
    )


def _splice_pair(window: DnaWindow, span: _Span, shift: int) -> SplicePair | None:
    dna = window.on_gene_strand
    donors = range(span.left_end - SPLICE_SLACK, span.left_end + SPLICE_SLACK + 1)
    lasts = range(span.right_start - 1 - SPLICE_SLACK, span.right_start + SPLICE_SLACK)
    fitting = [
        (abs(donor - span.left_end) + abs(last - span.right_start + 1), donor, last)
        for donor in donors
        for last in lasts
        if donor >= 0
        and last - donor + 1 >= MIN_INTRON
        and (last - donor + 1 - shift) % 3 == 0
        and f"{dna[donor : donor + 2]}..{dna[last - 1 : last + 1]}" in CANONICAL_MOTIFS
    ]
    if not fitting:
        return None
    _, donor, last = min(fitting)
    ends = sorted((window.genome_position(donor), window.genome_position(last)))
    motif = f"{dna[donor : donor + 2]}..{dna[last - 1 : last + 1]}"
    return SplicePair(motif=motif, donor=ends[0], acceptor=ends[1])


def _primitive(unit: str) -> bool:
    return (unit + unit).find(unit, 1) == len(unit)


def _explains(shift: int, unit: int) -> bool:
    return abs(shift) % unit == 0 and abs(shift) <= MAX_MISCOUNT_UNITS * unit


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
        while end + unit < stop and dna[end] == dna[end + unit] and dna[end] != _GAP:
            end += 1
        if end + unit > lo and at <= hi and end + unit - at >= least:
            found.append((at, end + unit))
        at = end + 1
    return found


def repeat_at(dna: str, lo: int, hi: int, shift: int) -> _Repeat | None:
    for units in ((1,), tuple(range(2, MAX_REPEAT_UNIT + 1))):
        found = [
            (end - start, -unit, -start, unit)
            for unit in units
            if _explains(shift, unit)
            for start, end in _stretches(dna, lo, hi, unit)
            if _primitive(dna[start : start + unit])
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


def _frame_change(
    reference: str,
    window: DnaWindow,
    code: GeneticCode,
    blocks: list[_Block],
    before: _Block,
    after: _Block,
) -> FrameChange:
    dna = window.on_gene_strand
    left, right = _diagonal(before[-1]), _diagonal(after[0])
    span = _span(reference, dna, code, before, after)
    repeat = repeat_at(dna, span.lo, span.hi, right - left)
    ends = sorted((window.genome_position(span.lo), window.genome_position(span.hi)))
    return FrameChange(
        source=window.source,
        strand=window.strand,
        start=ends[0],
        end=ends[1],
        frame_before=window.genome_frame(left),
        frame_after=window.genome_frame(right),
        shift=right - left,
        reference_residues=(span.first_cut + 1, span.last_cut + 1),
        run=None if repeat is None else _genome_run(window, repeat),
        splice_pair=_splice_pair(window, span, right - left),
        steps_between=(after[0][0] - before[-1][0]) // STEP,
        model_goes_on=any(_held(block) for block in blocks[blocks.index(after) :]),
    )


def _read_across(first: _Placed, second: _Placed) -> bool:
    return _diagonal(first) == _diagonal(second) and second[0] - first[0] == STEP


def _gap_between_parts(dna: str, placed: list[_Placed]) -> bool:
    return any(
        _GAP in dna[first[1].base : second[1].base + 3 * WINDOW]
        for first, second in pairwise(placed)
        if (first[1].beyond_model or second[1].beyond_model)
        and not _read_across(first, second)
    )


def _open(dna: str, code: GeneticCode, bases: list[int]) -> bool:
    return "*" not in translate(dna[min(bases) : max(bases) + 3 * WINDOW], code)


def _fits_anchor(dna: str, code: GeneticCode, anchor: _Placed, part: _Block) -> bool:
    return (
        len(part) == MIN_BLOCK_WINDOWS
        and all((_diagonal(hit) - _diagonal(anchor)) % 3 == 0 for hit in part)
        and _open(dna, code, [anchor[1].base, *(hit[1].base for hit in part)])
    )


def _parts_beyond(
    placed: list[_Placed],
) -> list[tuple[_Block, list[_Placed], list[_Placed]]]:
    runs = [
        list(run) for _, run in groupby(placed, key=lambda hit: hit[1].beyond_model)
    ]
    return [
        (
            run,
            runs[k - 1][-1:] if k else [],
            runs[k + 1][:1] if k + 1 < len(runs) else [],
        )
        for k, run in enumerate(runs)
        if run[0][1].beyond_model
    ]


def _part_in_open_frame(dna: str, code: GeneticCode, placed: list[_Placed]) -> bool:
    for run, before, after in _parts_beyond(placed):
        sides = [
            *((anchor, run[:MIN_BLOCK_WINDOWS]) for anchor in before),
            *((anchor, run[-MIN_BLOCK_WINDOWS:]) for anchor in after),
        ]
        if sides and all(_fits_anchor(dna, code, *side) for side in sides):
            return True
    return False


class PartRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    part_open: bool = False
    part_stop: int | None = None
    ns_in_part: int = 0


def _read_part(window: DnaWindow, code: GeneticCode, placed: list[_Placed]) -> PartRead:
    dna = window.on_gene_strand
    parts = _parts_beyond(placed)
    sides = [
        (anchor, run) for run, before, after in parts for anchor in (*before, *after)
    ]
    stops: list[int] = []
    ns = 0
    for anchor, run in sides:
        bases = [anchor[1].base, *(hit.base for _, hit in run)]
        low = min(bases) + (anchor[1].base - min(bases)) % 3
        stretch = dna[low : max(bases) + 3 * WINDOW]
        ns = max(ns, stretch.count(_GAP))
        protein = translate(stretch, code)
        if "*" in protein:
            stops.append(low + 3 * protein.index("*"))
    in_frame = all(
        (_diagonal(hit) - _diagonal(anchor)) % 3 == 0
        for anchor, run in sides
        for hit in run
    )
    every_part_anchored = all(before or after for _, before, after in parts)
    return PartRead(
        part_open=every_part_anchored and in_frame and not stops and not ns,
        part_stop=window.genome_position(min(stops)) if stops else None,
        ns_in_part=ns,
    )


class FrameRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    gapped: bool
    verdict: _EncodedVerdict
    frame_changes: list[FrameChange]
    unlisted_changes: list[FrameChange]
    part: PartRead


FRAMES_NOT_READ = FrameRead(
    gapped=False,
    verdict="OTHER_FRAME",
    frame_changes=[],
    unlisted_changes=[],
    part=PartRead(),
)


def read_frames(
    reference: str, track: SegmentTrack, window: DnaWindow, code: GeneticCode
) -> FrameRead:
    dna = window.on_gene_strand
    placed = [(k * STEP, hit) for k, hit in enumerate(track.hits) if hit is not None]
    gapped = _gap_between_parts(dna, placed)
    blocks = _blocks(track)
    changes = [pair for pair in pairwise(blocks) if _is_change(*pair)]
    read = [
        _frame_change(reference, window, code, blocks, before, after)
        for before, after in changes
    ]
    if _part_in_open_frame(dna, code, placed):
        verdict: _EncodedVerdict = "GENOME_ENCODES"
    elif any(change.run_explains_shift for change in read):
        verdict = "FRAMESHIFT"
    else:
        verdict = "OTHER_FRAME"
    ordered = sorted(read, key=lambda change: not change.run_explains_shift)
    return FrameRead(
        gapped=gapped,
        verdict=verdict,
        frame_changes=ordered[:MAX_FRAME_CHANGES],
        unlisted_changes=ordered[MAX_FRAME_CHANGES:],
        part=_read_part(window, code, placed),
    )


def _occurrences(dna: str, flank: str) -> int:
    count = 0
    at = dna.find(flank)
    while at >= 0:
        count += 1
        at = dna.find(flank, at + 1)
    return count


def _one_place(
    reference: str, strain: str, begin: int, end: int, *, left: bool
) -> tuple[str, int] | ReferenceMiss:
    for width in FLANK_WIDTHS:
        flank = (
            strain[max(0, begin - width) : begin] if left else strain[end : end + width]
        )
        if len(flank) < width:
            return "FLANK_SHORT"
        match _occurrences(reference, flank):
            case 0:
                return "FLANK_MISSING"
            case 1:
                return flank, reference.index(flank)
            case _:
                continue
    return "FLANK_REPEATED"


def flanked_span(
    strain: str, begin: int, end: int, reference: str
) -> tuple[int, int] | ReferenceMiss:
    match _one_place(reference, strain, begin, end, left=True):
        case (str() as left, int() as left_at):
            start = left_at + len(left)
        case miss:
            return miss
    match _one_place(reference, strain, begin, end, left=False):
        case (str(), int() as stop):
            pass
        case miss:
            return miss
    if stop < start or stop - start > MAX_REFERENCE_SPAN:
        return "FLANK_MISSING"
    return (start, stop) if stop > start else "EMPTY_SPAN"

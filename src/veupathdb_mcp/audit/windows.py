"""Twenty-residue window matching of a reference protein against models and DNA."""

from __future__ import annotations

from collections import Counter
from typing import Literal, Self

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view
from numpy.typing import NDArray
from pydantic import BaseModel, ConfigDict, model_validator
from veupathdb.model import CamelModel

from veupathdb_mcp.audit.codes import (
    Frame,
    GeneticCode,
    reverse_complement,
    six_frames,
)

WINDOW = 20
STEP = 10
FOUND = 0.5
MISSING = 0.35

type WindowState = Literal[
    "model", "genome_same_strand", "genome_other_strand", "absent", "weak"
]
type Strand = Literal["+", "-"]

_LETTER: dict[WindowState, str] = {
    "model": "M",
    "genome_same_strand": "G",
    "genome_other_strand": "g",
    "absent": ".",
    "weak": "w",
}
_READ_IN_DNA: frozenset[WindowState] = frozenset({"model", "genome_same_strand"})


def _encode(text: str) -> NDArray[np.uint8]:
    return np.frombuffer(text.encode(), dtype=np.uint8)


def best_identity(window: str, target: str) -> float:
    if len(target) < len(window):
        return 0.0
    views = sliding_window_view(_encode(target), len(window))
    hits = (views == _encode(window)).sum(axis=1)
    return float(hits.max()) / len(window)


class GenomeSource(CamelModel):
    model_config = ConfigDict(frozen=True)

    site: str
    organism: str
    seqid: str


class DnaWindow(BaseModel):
    model_config = ConfigDict(frozen=True)

    source: GenomeSource
    start: int
    sequence: str
    strand: Strand
    at_contig_edge: bool

    @property
    def ns(self) -> int:
        return self.sequence.upper().count("N")

    @property
    def on_gene_strand(self) -> str:
        if self.strand == "+":
            return self.sequence
        return reverse_complement(self.sequence)

    def genome_position(self, base: int) -> int:
        if self.strand == "+":
            return self.start + base
        return self.start + len(self.sequence) - 1 - base

    def gene_strand_base(self, position: int) -> int:
        if self.strand == "+":
            return position - self.start
        return self.start + len(self.sequence) - 1 - position

    def genome_frame(self, base: int) -> int:
        return (self.genome_position(base) - 1) % 3


class WindowHit(BaseModel):
    model_config = ConfigDict(frozen=True)

    base: int
    identity: float
    in_model: float

    @property
    def beyond_model(self) -> bool:
        return self.identity > self.in_model


class SegmentTrack(BaseModel):
    model_config = ConfigDict(frozen=True)

    states: list[WindowState]
    hits: list[WindowHit | None]

    @model_validator(mode="after")
    def _one_hit_per_window(self) -> Self:
        if len(self.hits) != len(self.states):
            msg = "a track holds one place in the DNA for each window"
            raise ValueError(msg)
        return self

    @property
    def counts(self) -> dict[WindowState, int]:
        return dict(Counter(self.states))

    @property
    def track(self) -> str:
        return "".join(_LETTER[s] for s in self.states)


def _nearest_hit(
    window: str, frames: list[Frame], expected: int | None, in_model: float
) -> WindowHit | None:
    scored: list[tuple[float, int]] = []
    letters = _encode(window)
    for frame in frames:
        if len(frame.protein) < len(window):
            continue
        views = sliding_window_view(_encode(frame.protein), len(window))
        hits = (views == letters).sum(axis=1)
        top = int(hits.max())
        scored += [
            (top / len(window), frame.offset + 3 * int(index))
            for index in np.flatnonzero(hits == top)
        ]
    identity = max((score for score, _ in scored), default=0.0)
    if identity < FOUND:
        return None
    tied = (base for score, base in scored if score == identity)
    if expected is None:
        return WindowHit(base=min(tied), identity=identity, in_model=in_model)
    base = min(tied, key=lambda at: (abs(at - expected), at))
    return WindowHit(base=base, identity=identity, in_model=in_model)


def _state(
    window: str, models: list[str], on_strand: str, off_strand: str
) -> tuple[WindowState, float]:
    in_model = max((best_identity(window, m) for m in models), default=0.0)
    if in_model >= FOUND:
        return "model", in_model
    if in_model >= MISSING:
        return "weak", in_model
    if best_identity(window, on_strand) >= FOUND:
        return "genome_same_strand", in_model
    if best_identity(window, off_strand) >= FOUND:
        return "genome_other_strand", in_model
    return "absent", in_model


def confirm_in_dna(
    reference: str,
    models: list[str],
    dna: str,
    strand: Strand,
    code: GeneticCode,
) -> SegmentTrack:
    frames = six_frames(dna, code)
    gap = "#" * WINDOW
    same = [f for f in frames if f.strand == strand]
    on_strand = gap.join(f.protein for f in same)
    off_strand = gap.join(f.protein for f in frames if f.strand != strand)
    states: list[WindowState] = []
    hits: list[WindowHit | None] = []
    diagonal: int | None = None
    for i in range(0, len(reference) - WINDOW + 1, STEP):
        window = reference[i : i + WINDOW]
        state, in_model = _state(window, models, on_strand, off_strand)
        states.append(state)
        expected = None if diagonal is None else diagonal + 3 * i
        hit = (
            _nearest_hit(window, same, expected, in_model)
            if state in _READ_IN_DNA
            else None
        )
        hits.append(hit)
        diagonal = diagonal if hit is None else hit.base - 3 * i
    return SegmentTrack(states=states, hits=hits)

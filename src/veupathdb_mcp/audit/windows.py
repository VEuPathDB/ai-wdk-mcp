"""Twenty-residue window matching of a reference protein against models and DNA."""

from __future__ import annotations

from collections import Counter
from typing import Literal

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view
from numpy.typing import NDArray
from pydantic import BaseModel, ConfigDict

from veupathdb_mcp.audit.codes import GeneticCode, six_frames

WINDOW = 20
STEP = 10
FOUND = 0.5
MISSING = 0.35

type WindowState = Literal[
    "model", "genome_same_strand", "genome_other_strand", "absent", "weak"
]

_LETTER: dict[WindowState, str] = {
    "model": "M",
    "genome_same_strand": "G",
    "genome_other_strand": "g",
    "absent": ".",
    "weak": "w",
}


def _encode(text: str) -> NDArray[np.uint8]:
    return np.frombuffer(text.encode(), dtype=np.uint8)


def best_identity(window: str, target: str) -> float:
    if len(target) < len(window):
        return 0.0
    views = sliding_window_view(_encode(target), len(window))
    hits = (views == _encode(window)).sum(axis=1)
    return float(hits.max()) / len(window)


class SegmentTrack(BaseModel):
    model_config = ConfigDict(frozen=True)

    states: list[WindowState]

    @property
    def counts(self) -> dict[WindowState, int]:
        return dict(Counter(self.states))

    @property
    def track(self) -> str:
        return "".join(_LETTER[s] for s in self.states)


def confirm_in_dna(
    reference: str,
    models: list[str],
    dna: str,
    strand: Literal["+", "-"],
    code: GeneticCode,
) -> SegmentTrack:
    frames = six_frames(dna, code)
    gap = "#" * WINDOW
    on_strand = gap.join(f.protein for f in frames if f.strand == strand)
    off_strand = gap.join(f.protein for f in frames if f.strand != strand)
    states: list[WindowState] = []
    for i in range(0, len(reference) - WINDOW + 1, STEP):
        window = reference[i : i + WINDOW]
        in_model = max((best_identity(window, m) for m in models), default=0.0)
        if in_model >= FOUND:
            states.append("model")
        elif in_model >= MISSING:
            states.append("weak")
        elif best_identity(window, on_strand) >= FOUND:
            states.append("genome_same_strand")
        elif best_identity(window, off_strand) >= FOUND:
            states.append("genome_other_strand")
        else:
            states.append("absent")
    return SegmentTrack(states=states)

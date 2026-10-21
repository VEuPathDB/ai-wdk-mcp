"""Whether the genome around a short or split gene model encodes the reference protein."""

from __future__ import annotations

from collections import Counter
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, model_validator
from veupathdb.model import CamelModel

from veupathdb_mcp.audit.codes import GeneticCode
from veupathdb_mcp.audit.windows import (
    STEP,
    WINDOW,
    SegmentTrack,
    WindowState,
    best_identity,
    confirm_in_dna,
)

type LengthVerdict = Literal[
    "GENOME_ENCODES",
    "ASSEMBLY",
    "ABSENT",
    "NOT_SHORT",
    "SPLIT_CONFIRMED",
    "SPLIT_UNCLEAR",
    "NOT_CHECKED",
]

type WindowLabel = WindowState | Literal["part1", "part2"]

ENCODED_WINDOWS = 3
ENCODED_SHARE = 0.5
SPLIT_PART_WINDOWS = 3
SPLIT_COVERED = 0.6
_MISSING: tuple[WindowLabel, ...] = (
    "genome_same_strand",
    "genome_other_strand",
    "absent",
)
_PARTS: tuple[WindowLabel, WindowLabel] = ("part1", "part2")


class DnaWindow(BaseModel):
    model_config = ConfigDict(frozen=True)

    sequence: str
    strand: Literal["+", "-"]
    at_contig_edge: bool

    @property
    def ns(self) -> int:
        return self.sequence.upper().count("N")


class LengthCheck(CamelModel):
    model_config = ConfigDict(frozen=True)

    verdict: LengthVerdict
    windows: int
    counts: dict[WindowLabel, int]
    track: str
    ns_in_window: int | None
    at_contig_edge: bool | None

    @model_validator(mode="after")
    def _window_facts(self) -> Self:
        unread = self.verdict == "NOT_CHECKED"
        if unread != (self.ns_in_window is None) or unread != (
            self.at_contig_edge is None
        ):
            msg = (
                "a check that reads the genome states its window facts, "
                "and a check that reads none states none"
            )
            raise ValueError(msg)
        return self

    @classmethod
    def not_checked(cls) -> LengthCheck:
        return cls(
            verdict="NOT_CHECKED",
            windows=0,
            counts={},
            track="",
            ns_in_window=None,
            at_contig_edge=None,
        )


def _labels(
    reference: str, models: list[str], track: SegmentTrack
) -> list[WindowLabel]:
    if len(models) == 1:
        return list(track.states)
    labels: list[WindowLabel] = []
    for k, state in enumerate(track.states):
        window = reference[k * STEP : k * STEP + WINDOW]
        scores = [best_identity(window, model) for model in models]
        part = _PARTS[scores.index(max(scores))]
        labels.append(part if state == "model" else state)
    return labels


def _letter(label: WindowLabel, letter: str) -> str:
    match label:
        case "part1":
            return "1"
        case "part2":
            return "2"
        case _:
            return letter


def _split(counts: Counter[WindowLabel], windows: int) -> LengthVerdict:
    first, second = counts["part1"], counts["part2"]
    if (
        min(first, second) >= SPLIT_PART_WINDOWS
        and first + second >= SPLIT_COVERED * windows
    ):
        return "SPLIT_CONFIRMED"
    return "SPLIT_UNCLEAR"


def _short(counts: Counter[WindowLabel], window: DnaWindow) -> LengthVerdict:
    missing = sum(counts[state] for state in _MISSING)
    same = counts["genome_same_strand"]
    if not missing:
        return "NOT_SHORT"
    if same >= ENCODED_WINDOWS and same >= ENCODED_SHARE * missing:
        return "GENOME_ENCODES"
    if window.ns or window.at_contig_edge:
        return "ASSEMBLY"
    return "ABSENT"


def check_length(
    reference: str, models: list[str], window: DnaWindow, code: GeneticCode
) -> LengthCheck:
    if len(models) not in {1, 2}:
        msg = f"a length check reads one model or two parts, not {len(models)}"
        raise ValueError(msg)
    track = confirm_in_dna(reference, models, window.sequence, window.strand, code)
    labels = _labels(reference, models, track)
    counts = Counter(labels)
    verdict = (
        _short(counts, window) if len(models) == 1 else _split(counts, len(labels))
    )
    return LengthCheck(
        verdict=verdict,
        windows=len(labels),
        counts=dict(counts),
        track="".join(
            _letter(label, letter)
            for label, letter in zip(labels, track.track, strict=True)
        ),
        ns_in_window=window.ns,
        at_contig_edge=window.at_contig_edge,
    )

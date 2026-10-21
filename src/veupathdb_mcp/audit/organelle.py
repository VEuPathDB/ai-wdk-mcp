"""Whether an organelle gene lies across the join of a circular genome stored as a line."""

from __future__ import annotations

from difflib import SequenceMatcher
from typing import Literal

import numpy as np
from numpy.typing import NDArray
from pydantic import BaseModel, ConfigDict
from veupathdb.model import CamelModel

from veupathdb_mcp.audit.codes import GeneticCode, six_frames

type OrganelleVerdict = Literal["SPLIT_AT_JOIN", "INTACT_ON_THE_LINE", "NOT_FOUND"]

ORGANELLE_MATCHED = 0.95
ORGANELLE_MIN_OVERLAP = 20
ORGANELLE_OVERLAP_AGREEMENT = 0.99
ORGANELLE_SHORT_PERIOD = 6
ORGANELLE_WORD = 4


class OrganelleCheck(CamelModel):
    model_config = ConfigDict(frozen=True)

    verdict: OrganelleVerdict
    best_linear: int
    best_circular: int
    reference_length: int
    overlap_bases: int
    overlap_mismatches: int


class EndOverlap(BaseModel):
    model_config = ConfigDict(frozen=True)

    bases: int
    mismatches: int


def _agreements(contig: str) -> NDArray[np.int64]:
    codes = np.frombuffer(contig.encode(), dtype=np.uint8)
    size = 1 << (2 * len(contig)).bit_length()
    total = np.zeros(len(contig))
    for base in set(contig) - {"N"}:
        spectrum = np.fft.rfft((codes == ord(base)).astype(np.float64), size)
        total += np.fft.irfft(spectrum * np.conj(spectrum), size)[: len(contig)]
    return np.rint(total).astype(np.int64)


def _prefix_periods(text: str) -> NDArray[np.int64]:
    borders = [0] * len(text)
    k = 0
    for i in range(1, len(text)):
        while k and text[i] != text[k]:
            k = borders[k - 1]
        if text[i] == text[k]:
            k += 1
        borders[i] = k
    return np.arange(1, len(text) + 1) - np.array(borders, dtype=np.int64)


def end_overlap(contig: str) -> EndOverlap:
    lengths = np.arange(ORGANELLE_MIN_OVERLAP, len(contig) // 2 + 1)
    if not lengths.size:
        return EndOverlap(bases=0, mismatches=0)
    agreed = _agreements(contig)[len(contig) - lengths]
    periods = _prefix_periods(contig[: len(contig) // 2])[lengths - 1]
    held = lengths[
        (agreed >= ORGANELLE_OVERLAP_AGREEMENT * lengths)
        & (periods > ORGANELLE_SHORT_PERIOD)
    ]
    if not held.size:
        return EndOverlap(bases=0, mismatches=0)
    bases = int(held.max())
    return EndOverlap(
        bases=bases, mismatches=bases - int(agreed[bases - ORGANELLE_MIN_OVERLAP])
    )


def _most_matched(dna: str, reference: str, code: GeneticCode) -> int:
    matcher = SequenceMatcher(None, "", reference, autojunk=False)
    frames = (
        orf for frame in six_frames(dna, code) for orf in frame.protein.split("*")
    )
    best = 0
    for orf in sorted(frames, key=len, reverse=True):
        if len(orf) <= best:
            break
        matcher.set_seq1(orf)
        blocks = matcher.get_matching_blocks()
        best = max(best, sum(b.size for b in blocks if b.size >= ORGANELLE_WORD))
    return best


def check_circular_join(
    contig: str, reference: str, code: GeneticCode
) -> OrganelleCheck:
    if not reference:
        msg = "the reference protein is empty"
        raise ValueError(msg)
    overlap = end_overlap(contig)
    circle = contig[: len(contig) - overlap.bases]
    if 3 * len(reference) > len(circle) // 2:
        msg = (
            f"the reference codes {len(reference)} residues, {3 * len(reference)} "
            f"bases, more than half of the {len(circle)}-base circle; a turn by "
            "half cannot place it whole"
        )
        raise ValueError(msg)
    half = len(circle) // 2
    linear = _most_matched(contig, reference, code)
    circular = _most_matched(circle[half:] + circle[:half], reference, code)
    needed = ORGANELLE_MATCHED * len(reference)
    verdict: OrganelleVerdict = "NOT_FOUND"
    if linear >= needed:
        verdict = "INTACT_ON_THE_LINE"
    elif circular >= needed:
        verdict = "SPLIT_AT_JOIN"
    return OrganelleCheck(
        verdict=verdict,
        best_linear=linear,
        best_circular=circular,
        reference_length=len(reference),
        overlap_bases=overlap.bases,
        overlap_mismatches=overlap.mismatches,
    )

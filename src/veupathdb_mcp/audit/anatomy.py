"""Where a pseudogene model's segments break, and what the genome holds at each break
and along the gene."""

from __future__ import annotations

import re
from bisect import bisect_left
from itertools import pairwise
from typing import Self

from pydantic import ConfigDict, model_validator
from veupathdb.model import CamelModel

from veupathdb_mcp.audit.gene_ids import GeneId, check_resolved
from veupathdb_mcp.audit.pseudogene import PseudogeneCheck
from veupathdb_mcp.computed import computed

RUN_REACH = 5
N_REACH = 100
RUN_PATTERN = re.compile(r"(.)\1*")


class Junction(CamelModel):
    model_config = ConfigDict(frozen=True)

    after: int
    before: int
    run_base: str
    run_length: int
    ns_within_100: int

    @model_validator(mode="after")
    def _advances(self) -> Self:
        if self.before <= self.after:
            msg = (
                f"the segments overlap: one ends at {self.after} and the next "
                f"starts at {self.before}"
            )
            raise ValueError(msg)
        return self

    @computed
    def gap(self) -> int:
        return self.before - self.after - 1

    @computed
    def gap_mod_3(self) -> int:
        return self.gap % 3


class ModelAnatomy(CamelModel):
    model_config = ConfigDict(frozen=True)

    segments: list[tuple[int, int]]
    junctions: list[Junction]
    to_contig_start: int
    to_contig_end: int
    ns_in_gene: int

    @model_validator(mode="after")
    def _tied(self) -> Self:
        for start, end in self.segments:
            if end < start:
                msg = f"the segment {start}-{end} ends before it starts"
                raise ValueError(msg)
        if len(self.junctions) != max(len(self.segments) - 1, 0):
            msg = (
                f"{len(self.segments)} segments and {len(self.junctions)} junctions; "
                "each pair of consecutive segments has one junction"
            )
            raise ValueError(msg)
        for ((_, end), (start, _)), junction in zip(
            pairwise(self.segments), self.junctions, strict=True
        ):
            if (junction.after, junction.before) != (end, start):
                msg = (
                    f"the junction {junction.after}-{junction.before} does not join "
                    f"the segment ending at {end} to the one starting at {start}"
                )
                raise ValueError(msg)
        return self


class Anatomy(ModelAnatomy):
    gene_ids: list[GeneId]
    strain_gene: str
    reference_gene: str
    reference_segments: int
    dna_check: PseudogeneCheck

    @model_validator(mode="after")
    def _named_as_resolved(self) -> Self:
        check_resolved(self.gene_ids, [self.strain_gene, self.reference_gene])
        return self


class _Genome:
    def __init__(self, window: str, start: int) -> None:
        self.window = window
        self.start = start
        self.end = start + len(window) - 1
        self.runs = [
            (start + m.start(), start + m.end() - 1, m.group(1))
            for m in RUN_PATTERN.finditer(window)
        ]
        self.run_ends = [end for _, end, _ in self.runs]

    def ns(self, first: int, last: int) -> int:
        lo, hi = max(first, self.start), min(last, self.end)
        return self.window[lo - self.start : hi - self.start + 1].count("N")

    def longest_run(self, reaches: list[tuple[int, int]]) -> tuple[str, int]:
        touching: list[tuple[int, int, str]] = []
        for lo, hi in reaches:
            index = bisect_left(self.run_ends, lo)
            while index < len(self.runs) and self.runs[index][0] <= hi:
                start, end, base = self.runs[index]
                touching.append((end - start + 1, -start, base))
                index += 1
        length, _, base = max(touching)
        return base, length


def _reaches(after: int, before: int, reach: int) -> list[tuple[int, int]]:
    first, last = sorted((after + 1, before - 1))
    if last - first <= 2 * reach + 1:
        return [(first - reach, last + reach)]
    return [(first - reach, first + reach), (last - reach, last + reach)]


def _junction(genome: _Genome, after: int, before: int) -> Junction:
    run_base, run_length = genome.longest_run(_reaches(after, before, RUN_REACH))
    return Junction(
        after=after,
        before=before,
        run_base=run_base,
        run_length=run_length,
        ns_within_100=sum(
            genome.ns(lo, hi) for lo, hi in _reaches(after, before, N_REACH)
        ),
    )


def pseudogene_anatomy(
    segments: list[tuple[int, int]], window: str, window_start: int, contig_length: int
) -> ModelAnatomy:
    if not segments:
        msg = "a model with no segment has no anatomy"
        raise ValueError(msg)
    ordered = sorted(segments)
    genome = _Genome(window, window_start)
    first, last = ordered[0][0], max(end for _, end in ordered)
    if first < genome.start or last > genome.end:
        msg = (
            f"the segments {first}-{last} lie outside the window "
            f"{genome.start}-{genome.end}"
        )
        raise ValueError(msg)
    return ModelAnatomy(
        segments=ordered,
        junctions=[_junction(genome, a, b) for (_, a), (b, _) in pairwise(ordered)],
        to_contig_start=first - 1,
        to_contig_end=contig_length - last,
        ns_in_gene=genome.ns(first, last),
    )

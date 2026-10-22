"""Annotated introns judged against the RNA-seq junctions over them, and the peptides,
motifs and depth that explain an annotated intron no junction reads."""

from __future__ import annotations

import statistics

from pydantic import BaseModel, ConfigDict

from veupathdb_mcp.audit.introns import (
    CANONICAL_MOTIFS,
    CHAIN_MAX_STEP,
    EXPRESSED_MIN_READS,
    INTRON_SLACK,
    MIN_INTRON,
    NO_EVIDENCE,
    REPLACED_MIN_SHARE,
    STRONG_MIN_READS,
    GeneStructure,
    IntronEvidence,
    IntronJudgement,
    IntronSupport,
    RnaJunction,
    Span,
    UnreadIntron,
    UnreadOutcome,
    verdict_of,
)


def _support(span: Span, junctions: list[RnaJunction]) -> IntronSupport:
    hits = [j for j in junctions if j.span == span]
    return IntronSupport(
        start=span[0],
        end=span[1],
        reads=max((j.reads for j in hits), default=0),
        tracks=len({j.track for j in hits}),
    )


def _floor(path: list[RnaJunction]) -> int:
    return min(j.reads for j in path)


def _extend(
    path: list[RnaJunction], usable: list[RnaJunction], end: int
) -> list[RnaJunction]:
    while abs(path[-1].end - end) > INTRON_SLACK:
        last = path[-1].end
        following = [
            j for j in usable if j.start > last + 1 and j.start - last < CHAIN_MAX_STEP
        ]
        if not following:
            break
        path = [*path, max(following, key=lambda j: j.reads)]
    return path


def _chain(intron: Span, junctions: list[RnaJunction]) -> list[RnaJunction]:
    start, end = intron
    usable = sorted(
        (
            j
            for j in junctions
            if j.usable
            and start - INTRON_SLACK <= j.start
            and j.end <= end + INTRON_SLACK
        ),
        key=lambda j: (j.start, j.end, j.reads),
    )
    best: list[RnaJunction] = []
    for first in usable:
        if abs(first.start - start) > INTRON_SLACK:
            continue
        path = _extend([first], usable, end)
        if abs(path[-1].end - end) <= INTRON_SLACK and (
            not best or _floor(path) > _floor(best)
        ):
            best = path
    return best


class _Gene(BaseModel):
    model_config = ConfigDict(frozen=True)

    model: GeneStructure
    introns: list[IntronSupport]
    same: list[RnaJunction]
    evidence: IntronEvidence

    @property
    def supported_median(self) -> float | None:
        reads = [i.reads for i in self.introns if i.reads]
        return statistics.median(reads) if reads else None

    def replacing(self, intron: Span) -> RnaJunction | None:
        floor = self.supported_median
        if floor is None:
            return None
        start, end = intron
        found = [
            j
            for j in self.same
            if j.usable
            and self.model.start <= j.start
            and j.end <= self.model.end
            and j.start <= end
            and j.end >= start
            and max(abs(j.start - start), abs(j.end - end)) > INTRON_SLACK
            and j.reads >= REPLACED_MIN_SHARE * floor
        ]
        return min(found, key=lambda j: (-j.reads, j.start, j.end), default=None)

    def others_read(self, intron: Span) -> bool:
        return all(
            i.reads >= STRONG_MIN_READS or self.cleared((i.start, i.end))
            for i in self.introns
            if (i.start, i.end) != intron
        )

    def cleared(self, intron: Span) -> bool:
        return (
            self.evidence.peptide_spans(intron)
            and not _chain(intron, self.same)
            and self.replacing(intron) is None
        )

    def unread(self, intron: Span) -> UnreadIntron:
        motif = self.evidence.motif_of(intron)
        depth = self.evidence.depth_of(intron)
        path = _chain(intron, self.same)
        links = path or [j for j in [self.replacing(intron)] if j is not None]
        outcome: UnreadOutcome
        if path:
            outcome = "SHIFTED" if len(path) == 1 else "MISSING_EXON"
        elif links:
            outcome = "REPLACED"
        elif motif is not None and motif not in CANONICAL_MOTIFS:
            outcome = "NONCANONICAL"
        elif depth is not None and depth.retained and self.others_read(intron):
            outcome = "RETAINED"
        else:
            outcome = "UNEXPLAINED"
        return UnreadIntron(
            start=intron[0],
            end=intron[1],
            in_cds=self.model.in_cds(intron),
            outcome=outcome,
            replacement=[_support(j.span, self.same) for j in links],
            motif=motif,
            depth=depth,
        )


def _expression(
    model: GeneStructure, introns: list[IntronSupport], same: list[RnaJunction]
) -> int:
    if any(i.reads for i in introns):
        return max(i.reads for i in introns)
    return max(
        (
            j.reads
            for j in same
            if j.strong and model.start <= j.start and j.end <= model.end
        ),
        default=0,
    )


def judge_introns(
    model: GeneStructure,
    junctions: list[RnaJunction],
    evidence: IntronEvidence = NO_EVIDENCE,
) -> IntronJudgement:
    inside = [j for j in junctions if model.start <= j.start and j.end <= model.end]
    unstranded = sum(j.strand not in {"+", "-"} for j in inside)
    if inside and unstranded == len(inside):
        return IntronJudgement.not_checked(
            f"every junction over {model.transcript} is unstranded "
            f"({unstranded} junctions)",
            unstranded,
        )
    same = [j for j in junctions if j.strand == model.strand]
    introns = [_support(span, same) for span in model.introns]
    best = _expression(model, introns, same)
    if best < EXPRESSED_MIN_READS:
        return IntronJudgement(
            verdict="NOT_EXPRESSED",
            introns=introns,
            unread=None,
            best_junction_reads=best,
            unstranded_ignored=unstranded,
        )
    gene = _Gene(model=model, introns=introns, same=same, evidence=evidence)
    unread = [
        gene.unread((i.start, i.end))
        for i in introns
        if not i.reads
        and i.end - i.start + 1 >= MIN_INTRON
        and not gene.cleared((i.start, i.end))
    ]
    return IntronJudgement(
        verdict=verdict_of(unread) if unread else "SUPPORTED",
        introns=introns,
        unread=unread,
        best_junction_reads=best,
        unstranded_ignored=unstranded,
    )


def _unexplained(judgement: IntronJudgement) -> list[UnreadIntron]:
    return [u for u in judgement.unread or [] if u.outcome == "UNEXPLAINED"]


def needs_peptides(judgement: IntronJudgement) -> bool:
    return bool(_unexplained(judgement))


def needs_motifs(judgement: IntronJudgement) -> list[Span]:
    return [u.span for u in _unexplained(judgement) if u.motif is None]


def needs_depth(judgement: IntronJudgement) -> list[Span]:
    return [u.span for u in _unexplained(judgement) if u.depth is None]

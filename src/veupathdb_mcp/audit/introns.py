"""Annotated introns of a gene model against the RNA-seq junctions a site serves,
and the model the strong junctions imply when annotated introns have no read."""

from __future__ import annotations

from itertools import pairwise
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator
from veupathdb.errors import DataParsingError
from veupathdb.jbrowse import GenomeWindow, GffFeature
from veupathdb.model import CamelModel

from veupathdb_mcp.audit.codes import GeneticCode, reverse_complement, translate
from veupathdb_mcp.audit.gene_ids import GeneId, check_resolved
from veupathdb_mcp.audit.introns_orthologs import OrthologSupport

STRONG_MIN_READS = 20
EXPRESSED_MIN_READS = 50
MIN_INTRON = 20
INTRON_SLACK = 30
STRONG_EVIDENCE = "Strong Evidence"
CHAIN_MAX_STEP = 2000

type Span = tuple[int, int]
type Strand = Literal["+", "-"]
type UnreadOutcome = Literal["SHIFTED", "MISSING_EXON", "UNEXPLAINED"]
type IntronVerdict = Literal[
    "SUPPORTED",
    "UNSUPPORTED_SHIFTED",
    "UNSUPPORTED_MISSING_EXON",
    "UNSUPPORTED_UNEXPLAINED",
    "NOT_EXPRESSED",
    "NOT_CHECKED",
]

CORRECTABLE: frozenset[IntronVerdict] = frozenset(
    {"UNSUPPORTED_SHIFTED", "UNSUPPORTED_MISSING_EXON"}
)
_FLAGGED: frozenset[IntronVerdict] = frozenset(
    {"UNSUPPORTED_SHIFTED", "UNSUPPORTED_MISSING_EXON", "UNSUPPORTED_UNEXPLAINED"}
)
_UNJUDGED: frozenset[IntronVerdict] = frozenset({"NOT_EXPRESSED", "NOT_CHECKED"})


class _JunctionTags(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    totalscore: tuple[float]
    evidence: tuple[str]


class RnaJunction(BaseModel):
    model_config = ConfigDict(frozen=True)

    start: int
    end: int
    strand: Literal["+", "-", ".", "?"]
    reads: int
    strong: bool
    track: str

    @classmethod
    def from_feature(cls, feature: GffFeature, track: str) -> RnaJunction:
        tags = _JunctionTags.model_validate(feature.attributes)
        return cls(
            start=feature.start,
            end=feature.end,
            strand=feature.strand,
            reads=int(tags.totalscore[0]),
            strong=tags.evidence == (STRONG_EVIDENCE,),
            track=track,
        )

    @property
    def span(self) -> Span:
        return self.start, self.end

    @property
    def usable(self) -> bool:
        return self.strong and self.reads >= STRONG_MIN_READS


class GeneStructure(BaseModel):
    model_config = ConfigDict(frozen=True)

    transcript: str
    other_transcripts: int = Field(ge=0)
    strand: Strand
    start: int
    end: int
    exons: list[Span] = Field(min_length=1)
    cds: list[Span] = Field(min_length=1)

    @model_validator(mode="after")
    def _in_the_gene(self) -> Self:
        spans = [*self.exons, *self.cds]
        if not all(self.start <= a <= b <= self.end for a, b in spans):
            msg = f"{self.transcript} has a part outside {self.start}-{self.end}"
            raise ValueError(msg)
        return self

    @property
    def introns(self) -> list[Span]:
        return [
            (a[1] + 1, b[0] - 1)
            for a, b in pairwise(sorted(self.exons))
            if b[0] - a[1] > 1
        ]

    @property
    def start_edge(self) -> int:
        if self.strand == "+":
            return min(start for start, _ in self.cds)
        return max(end for _, end in self.cds)

    def in_cds(self, intron: Span) -> bool:
        return min(a for a, _ in self.cds) < intron[0] and intron[1] < max(
            b for _, b in self.cds
        )


class IntronSupport(CamelModel):
    model_config = ConfigDict(frozen=True)

    start: int
    end: int
    reads: int
    tracks: int


def _fits(outcome: UnreadOutcome, links: int) -> bool:
    match outcome:
        case "SHIFTED":
            return links == 1
        case "MISSING_EXON":
            return links > 1
        case "UNEXPLAINED":
            return links == 0


class UnreadIntron(CamelModel):
    model_config = ConfigDict(frozen=True)

    start: int
    end: int
    in_cds: bool
    outcome: UnreadOutcome
    replacement: list[IntronSupport]

    @model_validator(mode="after")
    def _replaced_as_named(self) -> Self:
        if not _fits(self.outcome, len(self.replacement)):
            msg = (
                f"a {self.outcome} intron has {len(self.replacement)} replacement "
                "junctions; SHIFTED has one, MISSING_EXON more, UNEXPLAINED none"
            )
            raise ValueError(msg)
        return self

    @property
    def span(self) -> Span:
        return self.start, self.end


def _verdict(unread: list[UnreadIntron]) -> IntronVerdict:
    outcomes = {u.outcome for u in unread}
    if "UNEXPLAINED" in outcomes:
        return "UNSUPPORTED_UNEXPLAINED"
    if "MISSING_EXON" in outcomes:
        return "UNSUPPORTED_MISSING_EXON"
    return "UNSUPPORTED_SHIFTED"


class IntronJudgement(CamelModel):
    model_config = ConfigDict(frozen=True)

    verdict: IntronVerdict
    introns: list[IntronSupport] | None
    unread: list[UnreadIntron] | None
    best_junction_reads: int | None
    unstranded_ignored: int = Field(default=0, ge=0)
    reason: str | None = None

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        unchecked = self.verdict == "NOT_CHECKED"
        named = _verdict(self.unread) if self.unread else None
        facts = (
            unchecked
            == (self.reason is not None)
            == (self.best_junction_reads is None)
            == (self.introns is None),
            (self.verdict in _UNJUDGED) == (self.unread is None),
            (self.verdict in _FLAGGED) == bool(self.unread),
            named in {None, self.verdict},
        )
        if not all(facts):
            msg = (
                f"a {self.verdict} judgement names its unread introns, its best "
                "junction and its reason exactly when it has them"
            )
            raise ValueError(msg)
        return self

    @classmethod
    def not_checked(cls, reason: str, unstranded: int = 0) -> IntronJudgement:
        return cls(
            verdict="NOT_CHECKED",
            introns=None,
            unread=None,
            best_junction_reads=None,
            unstranded_ignored=unstranded,
            reason=reason,
        )


class IntronCorrection(CamelModel):
    model_config = ConfigDict(frozen=True)

    cds: list[Span]
    protein: str
    frame_kept: bool


class IntronAudit(IntronJudgement):
    gene_ids: list[GeneId]
    gene: str
    transcript: str | None
    other_transcripts: int | None
    tracks_refused: list[str] | None
    corrected_cds: list[Span] | None
    corrected_protein: str | None
    frame_kept: bool | None
    code: GeneticCode | None
    code_inferred: bool
    orthologs: OrthologSupport | None
    correction_reason: str | None = None

    @model_validator(mode="after")
    def _named_as_resolved(self) -> Self:
        check_resolved(self.gene_ids, [self.gene])
        return self

    @model_validator(mode="after")
    def _corrected_as_judged(self) -> Self:
        correctable = self.verdict in CORRECTABLE
        corrected = correctable and self.correction_reason is None
        facts = (
            correctable or self.correction_reason is None,
            {
                value is None
                for value in (
                    self.corrected_cds,
                    self.corrected_protein,
                    self.frame_kept,
                    self.code,
                    self.orthologs,
                )
            }
            == {not corrected},
            corrected or not self.code_inferred,
            (self.transcript is None) == (self.other_transcripts is None),
        )
        if not all(facts):
            msg = (
                "an audit translates, reads a code and counts orthologs exactly "
                "when every unread intron is explained and the correction was "
                "read, and names a correction reason only for such a verdict"
            )
            raise ValueError(msg)
        return self


class _Orf(BaseModel):
    model_config = ConfigDict(frozen=True)

    protein: str
    stop: bool
    positions: list[int]


def _merge(spans: list[Span]) -> list[Span]:
    merged: list[Span] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _subtract(spans: list[Span], cuts: list[Span]) -> list[Span]:
    kept = _merge(spans)
    for cut_start, cut_end in cuts:
        kept = [
            piece
            for start, end in kept
            for piece in (
                (start, min(end, cut_start - 1)),
                (max(start, cut_end + 1), end),
            )
            if piece[0] <= piece[1]
        ]
    return kept


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


def _unread(
    model: GeneStructure, intron: IntronSupport, same: list[RnaJunction]
) -> UnreadIntron:
    path = _chain((intron.start, intron.end), same)
    outcome: UnreadOutcome = (
        "UNEXPLAINED" if not path else "SHIFTED" if len(path) == 1 else "MISSING_EXON"
    )
    return UnreadIntron(
        start=intron.start,
        end=intron.end,
        in_cds=model.in_cds((intron.start, intron.end)),
        outcome=outcome,
        replacement=[_support(j.span, same) for j in path],
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
    model: GeneStructure, junctions: list[RnaJunction]
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
    unread = [
        _unread(model, i, same)
        for i in introns
        if not i.reads and i.end - i.start + 1 >= MIN_INTRON
    ]
    return IntronJudgement(
        verdict=_verdict(unread) if unread else "SUPPORTED",
        introns=introns,
        unread=unread,
        best_junction_reads=best,
        unstranded_ignored=unstranded,
    )


def _complement(bases: str) -> str:
    return reverse_complement(bases)[::-1]


def _orf(
    dna: GenomeWindow, exons: list[Span], strand: Strand, edge: int, code: GeneticCode
) -> _Orf:
    exonic = [p for start, end in _merge(exons) for p in range(start, end + 1)]
    if strand == "+":
        path = [p for p in exonic if p >= edge] + list(
            range(exonic[-1] + 1, dna.end + 1)
        )
    else:
        path = [p for p in reversed(exonic) if p <= edge] + list(
            range(exonic[0] - 1, dna.start - 1, -1)
        )
    bases = "".join(dna.sequence[p - dna.start] for p in path)
    residues = translate(bases if strand == "+" else _complement(bases), code)
    protein, stop, _ = residues.partition("*")
    used = 3 * (len(protein) + 1) if stop else 3 * len(protein)
    return _Orf(protein=protein, stop=bool(stop), positions=path[:used])


def correct_model(
    model: GeneStructure,
    unread: list[UnreadIntron],
    dna: GenomeWindow,
    code: GeneticCode,
) -> IntronCorrection:
    if not unread or any(u.outcome == "UNEXPLAINED" for u in unread):
        msg = "a model is corrected only when every unread intron is explained"
        raise ValueError(msg)
    parts = [*model.exons, *model.cds]
    if not dna.start <= min(a for a, _ in parts) <= max(b for _, b in parts) <= dna.end:
        msg = (
            f"{model.transcript} lies outside the window "
            f"{dna.seqid}:{dna.start}-{dna.end}"
        )
        raise DataParsingError(msg)
    exons = _subtract(
        [*model.exons, *(u.span for u in unread)],
        [(r.start, r.end) for u in unread for r in u.replacement],
    )
    annotated = _orf(dna, model.exons, model.strand, model.start_edge, code)
    corrected = _orf(dna, exons, model.strand, model.start_edge, code)
    return IntronCorrection(
        cds=_merge([(p, p) for p in corrected.positions]),
        protein=corrected.protein,
        frame_kept=annotated.stop
        and corrected.stop
        and annotated.positions[-3:] == corrected.positions[-3:],
    )

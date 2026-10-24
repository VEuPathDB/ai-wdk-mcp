"""Annotated introns of a gene model against the RNA-seq junctions a site serves, and
the peptides, splice motifs and read depth that explain an annotated intron no read
spans."""

from __future__ import annotations

from itertools import pairwise
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator
from veupathdb.jbrowse import GffFeature
from veupathdb.model import CamelModel

from veupathdb_mcp.audit.codes import GeneticCode
from veupathdb_mcp.audit.gene_ids import GeneId, check_resolved
from veupathdb_mcp.audit.gene_models import ModelSpans, check_models
from veupathdb_mcp.audit.introns_orthologs import OrthologSupport
from veupathdb_mcp.computed import computed

STRONG_MIN_READS = 20
EXPRESSED_MIN_READS = 50
MIN_INTRON = 20
INTRON_SLACK = 30
STRONG_EVIDENCE = "Strong Evidence"
CHAIN_MAX_STEP = 2000
REPLACED_MIN_SHARE = 0.25
RETAINED_MIN_SHARE = 0.25
RETAINED_MIN_COVERED = 0.9
PEPTIDE_SLACK = 3
CANONICAL_MOTIFS = frozenset({"GT..AG", "GC..AG"})
JUNCTION_TRACKS_READ = 4

type Span = tuple[int, int]
type Strand = Literal["+", "-"]
type UnreadOutcome = Literal[
    "SHIFTED", "MISSING_EXON", "REPLACED", "NONCANONICAL", "RETAINED", "UNEXPLAINED"
]
type IntronVerdict = Literal[
    "SUPPORTED",
    "UNSUPPORTED_SHIFTED",
    "UNSUPPORTED_MISSING_EXON",
    "UNSUPPORTED_REPLACED",
    "UNSUPPORTED_NONCANONICAL",
    "UNSUPPORTED_RETAINED",
    "UNSUPPORTED_UNEXPLAINED",
    "NOT_EXPRESSED",
    "NOT_CHECKED",
]

CORRECTABLE: frozenset[IntronVerdict] = frozenset(
    {
        "UNSUPPORTED_SHIFTED",
        "UNSUPPORTED_MISSING_EXON",
        "UNSUPPORTED_REPLACED",
        "UNSUPPORTED_NONCANONICAL",
        "UNSUPPORTED_RETAINED",
    }
)
_FLAGGED: frozenset[IntronVerdict] = CORRECTABLE | {"UNSUPPORTED_UNEXPLAINED"}
_RANKED: tuple[tuple[UnreadOutcome, IntronVerdict], ...] = (
    ("UNEXPLAINED", "UNSUPPORTED_UNEXPLAINED"),
    ("NONCANONICAL", "UNSUPPORTED_NONCANONICAL"),
    ("RETAINED", "UNSUPPORTED_RETAINED"),
    ("MISSING_EXON", "UNSUPPORTED_MISSING_EXON"),
    ("REPLACED", "UNSUPPORTED_REPLACED"),
    ("SHIFTED", "UNSUPPORTED_SHIFTED"),
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


def within_exons(cds: list[Span] | None, exons: list[Span] | None) -> bool:
    return exons is None or (
        cds is not None
        and all(any(a <= start and end <= b for a, b in exons) for start, end in cds)
    )


def intron_key(span: Span) -> str:
    return f"{span[0]}-{span[1]}"


class PeptideSplit(CamelModel):
    model_config = ConfigDict(frozen=True)

    before: Span
    after: Span

    @model_validator(mode="after")
    def _in_order(self) -> Self:
        if not self.before[0] <= self.before[1] < self.after[0] <= self.after[1]:
            msg = f"a split peptide reads {self.before} before {self.after}"
            raise ValueError(msg)
        return self

    def spans(self, intron: Span) -> bool:
        gap = (self.before[1] + 1, self.after[0] - 1)
        return all(
            abs(a - b) <= PEPTIDE_SLACK for a, b in zip(gap, intron, strict=True)
        )


class IntronDepth(CamelModel):
    model_config = ConfigDict(frozen=True)

    intron_median_depth: float
    exon_median_depth: float
    covered_share: float = Field(ge=0, le=1)
    track: str

    @computed
    def depth_share(self) -> float:
        if self.exon_median_depth == 0:
            return 0.0
        return round(self.intron_median_depth / self.exon_median_depth, 3)

    @property
    def retained(self) -> bool:
        return (
            self.exon_median_depth > 0
            and self.intron_median_depth >= RETAINED_MIN_SHARE * self.exon_median_depth
            and self.covered_share >= RETAINED_MIN_COVERED
        )


class IntronEvidence(CamelModel):
    model_config = ConfigDict(frozen=True)

    peptides: tuple[PeptideSplit, ...] | None = None
    motifs: dict[str, str] | None = None
    depth: dict[str, IntronDepth] | None = None
    gaps: tuple[str, ...] = ()

    def over_gap(self, intron: Span) -> bool:
        return intron_key(intron) in self.gaps

    def peptide_spans(self, intron: Span) -> bool:
        return any(peptide.spans(intron) for peptide in self.peptides or ())

    def motif_of(self, intron: Span) -> str | None:
        return (self.motifs or {}).get(intron_key(intron))

    def depth_of(self, intron: Span) -> IntronDepth | None:
        return (self.depth or {}).get(intron_key(intron))


NO_EVIDENCE = IntronEvidence()


def _fits(outcome: UnreadOutcome, links: int) -> bool:
    match outcome:
        case "SHIFTED" | "REPLACED":
            return links == 1
        case "MISSING_EXON":
            return links > 1
        case "NONCANONICAL" | "RETAINED" | "UNEXPLAINED":
            return links == 0


class UnreadIntron(CamelModel):
    model_config = ConfigDict(frozen=True)

    start: int
    end: int
    in_cds: bool
    outcome: UnreadOutcome
    replacement: list[IntronSupport]
    motif: str | None = None
    depth: IntronDepth | None = None
    spans_assembly_gap: bool = False

    @model_validator(mode="after")
    def _replaced_as_named(self) -> Self:
        if not _fits(self.outcome, len(self.replacement)):
            msg = (
                f"a {self.outcome} intron has {len(self.replacement)} replacement "
                "junctions; SHIFTED and REPLACED have one, MISSING_EXON more, "
                "NONCANONICAL, RETAINED and UNEXPLAINED none"
            )
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _kept_as_read(self) -> Self:
        facts = (
            self.outcome != "NONCANONICAL"
            or (self.motif is not None and self.motif not in CANONICAL_MOTIFS),
            self.outcome != "RETAINED" or self.depth is not None,
        )
        if not all(facts):
            msg = (
                f"a {self.outcome} intron carries the evidence that kept it: a "
                "NONCANONICAL one its motif, a RETAINED one its depth"
            )
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _gap_left_unread(self) -> Self:
        if self.spans_assembly_gap and (self.motif, self.depth) != (None, None):
            msg = (
                f"a {self.outcome} intron over an assembly gap carries a motif or "
                "a depth; the genome over a gap gives neither"
            )
            raise ValueError(msg)
        return self

    @property
    def span(self) -> Span:
        return self.start, self.end

    @property
    def assembly_gap_note(self) -> str | None:
        if not self.spans_assembly_gap:
            return None
        return f"the intron {self.start}-{self.end} spans an assembly gap"


class JunctionTracks(CamelModel):
    model_config = ConfigDict(frozen=True)

    organism_abbrev: str
    listed: int = Field(ge=0)
    read: int = Field(ge=0)

    @model_validator(mode="after")
    def _read_from_the_list(self) -> Self:
        if self.read > self.listed:
            msg = (
                f"{self.organism_abbrev} lists {self.listed} junction tracks and "
                f"cannot read {self.read}"
            )
            raise ValueError(msg)
        return self

    @property
    def cap_note(self) -> str | None:
        if self.read >= self.listed:
            return None
        return (
            f"{self.organism_abbrev} lists {self.listed} junction tracks; the first "
            f"{self.read} were read"
        )


def verdict_of(unread: list[UnreadIntron]) -> IntronVerdict:
    outcomes = {u.outcome for u in unread}
    return next(verdict for outcome, verdict in _RANKED if outcome in outcomes)


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
        named = verdict_of(self.unread) if self.unread else None
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


class IntronAudit(IntronJudgement):
    gene_ids: list[GeneId]
    gene: str
    transcript: str | None
    other_transcripts: int | None
    tracks_refused: list[str] | None
    evidence_unread: list[str]
    corrected_cds: list[Span] | None
    corrected_protein: str | None
    frame_kept: bool | None
    code: GeneticCode | None
    code_inferred: bool
    orthologs: OrthologSupport | None
    correction_reason: str | None = None
    corrected_exons: list[Span] | None = None
    model: ModelSpans | None = None
    junction_tracks: JunctionTracks | None = None

    @model_validator(mode="after")
    def _named_as_resolved(self) -> Self:
        check_resolved(self.gene_ids, [self.gene])
        check_models([self.model] if self.model else [], [self.gene])
        return self

    @model_validator(mode="after")
    def _cut_named(self) -> Self:
        note = self.junction_tracks.cap_note if self.junction_tracks else None
        if note is not None and note not in self.evidence_unread:
            msg = f"an intron audit names its junction track cut: {note}"
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _transcribed_as_corrected(self) -> Self:
        if not within_exons(self.corrected_cds, self.corrected_exons):
            msg = (
                "an intron audit names corrected exons only with a corrected CDS "
                "that lies inside its exons"
            )
            raise ValueError(msg)
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

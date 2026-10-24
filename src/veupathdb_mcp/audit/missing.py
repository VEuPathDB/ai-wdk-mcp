"""Whether the DNA between two conserved neighbours of a gene holds that gene in a
genome whose annotation lacks it."""

from __future__ import annotations

import difflib
from collections import Counter, defaultdict
from typing import Literal, Self

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view
from numpy.typing import NDArray
from pydantic import BaseModel, ConfigDict, Field, model_validator
from veupathdb.model import CamelModel

from veupathdb_mcp.audit.codes import Frame, GeneticCode, six_frames
from veupathdb_mcp.audit.gene_ids import GeneId, check_resolved
from veupathdb_mcp.audit.genes import GeneRow, contig_sides
from veupathdb_mcp.audit.lengths import is_orthology_group
from veupathdb_mcp.audit.windows import FOUND, MISSING, STEP, WINDOW
from veupathdb_mcp.computed import computed
from veupathdb_mcp.tool_meta import Share

type MissingVerdict = Literal[
    "IN_DNA_UNANNOTATED",
    "IN_DNA_OTHER_MODEL",
    "PARTIAL",
    "GAP",
    "NOT_IN_DNA",
    "NO_SYNTENY",
    "ANNOTATED_IN_GENOME",
]
_UNREAD: frozenset[MissingVerdict] = frozenset({"NO_SYNTENY", "ANNOTATED_IN_GENOME"})

ANCHOR_REACH = 6
ANCHOR_MAX_SPAN = 60_000
MISSING_PAD = 3000
IN_DNA_SHARE = 0.6
GAP_NS = 100


class Anchor(CamelModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    neighbour: str
    gene: str
    sequence_id: str
    start: int
    end: int
    strand: Literal["+", "-"]


def _bounds(left: Anchor, right: Anchor) -> tuple[int, int]:
    low, high = sorted((min(left.end, right.end), max(left.start, right.start)))
    return low, high


def _joinable(left: Anchor, right: Anchor) -> bool:
    low, high = _bounds(left, right)
    return left.sequence_id == right.sequence_id and high - low <= ANCHOR_MAX_SPAN


class Anchors(CamelModel):
    model_config = ConfigDict(frozen=True)

    left: Anchor
    right: Anchor

    @model_validator(mode="after")
    def _one_contig_nearby(self) -> Self:
        if not _joinable(self.left, self.right):
            msg = (
                f"the anchors {self.left.gene} and {self.right.gene} do not lie on "
                f"one contig within {ANCHOR_MAX_SPAN} bases"
            )
            raise ValueError(msg)
        return self

    @computed
    def between(self) -> tuple[int, int]:
        return _bounds(self.left, self.right)


class Located(CamelModel):
    model_config = ConfigDict(frozen=True)

    windows: int = Field(ge=1)
    found: int = Field(ge=0)
    span: tuple[int, int] | None
    ns: int

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.found > self.windows or (self.span is None) != (self.found == 0):
            msg = (
                f"{self.found} found of {self.windows} windows cannot give "
                f"the span {self.span}"
            )
            raise ValueError(msg)
        return self

    @computed
    def share(self) -> Share:
        return round(self.found / self.windows, 3)


class OpenFrame(CamelModel):
    model_config = ConfigDict(frozen=True)

    length: int
    identical: int


class MissingScan(BaseModel):
    model_config = ConfigDict(frozen=True)

    located: Located
    open_frame: OpenFrame | None
    stops: list[int]
    intact_frame: bool | None

    @model_validator(mode="after")
    def _read_when_found(self) -> Self:
        if (self.located.span is None) != (self.intact_frame is None):
            msg = "a scan reads a frame exactly when it finds a window"
            raise ValueError(msg)
        return self


class _Hit(BaseModel):
    model_config = ConfigDict(frozen=True)

    residue: int
    frame: Frame
    at: int

    @property
    def shift(self) -> int:
        return self.at - self.residue


class OverlappingGene(CamelModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    gene: str
    product: str
    ortholog_group: str
    protein_length: int | None
    start: int
    end: int
    strand: Literal["+", "-"]
    pseudo: bool | None
    gene_type: str


class AnnotatedMember(CamelModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    gene: str
    sequence_id: str
    start: int


def group_members(example: GeneRow, genome: list[GeneRow]) -> list[GeneRow] | None:
    group = example.ortholog_group
    if not is_orthology_group(group):
        return None
    return sorted(
        (row for row in genome if row.ortholog_group == group),
        key=lambda row: (row.sequence_id, row.start, row.gene),
    )


class MissingGeneAudit(CamelModel):
    model_config = ConfigDict(frozen=True)

    verdict: MissingVerdict
    gene_ids: list[GeneId]
    example_gene: str
    absent_organism: str
    example_length: int
    annotated_members: list[AnnotatedMember] | None
    anchors: Anchors | None
    located: Located | None
    overlapping: list[OverlappingGene] | None
    open_frame: OpenFrame | None
    stops: list[int] | None
    intact_frame: bool | None
    code: GeneticCode | None
    code_inferred: bool

    @model_validator(mode="after")
    def _named_as_resolved(self) -> Self:
        check_resolved(self.gene_ids, [self.example_gene])
        return self

    @model_validator(mode="after")
    def _members_when_annotated(self) -> Self:
        if bool(self.annotated_members) != (self.verdict == "ANNOTATED_IN_GENOME"):
            msg = (
                "an ANNOTATED_IN_GENOME audit, and only that one, names the absent "
                "genome's members of the example's group"
            )
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _read_when_anchored(self) -> Self:
        unread = self.verdict in _UNREAD
        read = (self.anchors, self.located, self.overlapping, self.stops, self.code)
        if any(unread != (fact is None) for fact in read) or (
            unread and self.code_inferred
        ):
            msg = (
                "a NO_SYNTENY or ANNOTATED_IN_GENOME audit, and only those, reads no "
                "genome: no anchors, located, overlapping, stops or code, and "
                "codeInferred false"
            )
            raise ValueError(msg)
        return self


def _walk(neighbours: list[GeneRow], example: GeneRow) -> list[list[GeneRow]]:
    return [
        [row for row in side if is_orthology_group(row.ortholog_group)]
        for side in contig_sides(example, neighbours, ANCHOR_REACH)
    ]


def find_anchors(
    neighbours: list[GeneRow], example: GeneRow, absent_genes: list[GeneRow]
) -> Anchors | None:
    members: defaultdict[str, list[GeneRow]] = defaultdict(list)
    for row in absent_genes:
        members[row.ortholog_group].append(row)
    picked = [
        next(
            (
                Anchor.model_validate(
                    {
                        **members[row.ortholog_group][0].model_dump(),
                        "neighbour": row.gene,
                    }
                )
                for row in side
                if len(members[row.ortholog_group]) == 1
            ),
            None,
        )
        for side in _walk(neighbours, example)
    ]
    match picked:
        case [Anchor() as left, Anchor() as right] if (
            left.gene != right.gene and _joinable(left, right)
        ):
            return Anchors(left=left, right=right)
        case _:
            return None


def overlapping(genes: list[GeneRow], span: tuple[int, int] | None) -> list[GeneRow]:
    if span is None:
        return []
    return [row for row in genes if row.end >= span[0] and row.start <= span[1]]


def _encode(text: str) -> NDArray[np.uint8]:
    return np.frombuffer(text.encode(), dtype=np.uint8)


def _hits(protein: str, frames: list[Frame]) -> tuple[int, list[_Hit]]:
    views = [
        (frame, sliding_window_view(_encode(frame.protein), WINDOW))
        for frame in frames
        if len(frame.protein) >= WINDOW
    ]
    starts = range(0, len(protein) - WINDOW + 1, STEP)
    hits: list[_Hit] = []
    for i in starts:
        piece = _encode(protein[i : i + WINDOW])
        best: _Hit | None = None
        score = 0
        for frame, view in views:
            counts = (view == piece).sum(axis=1)
            k = int(counts.argmax())
            if best is None or int(counts[k]) > score:
                best, score = _Hit(residue=i, frame=frame, at=k), int(counts[k])
        if best is not None and score >= FOUND * WINDOW:
            hits.append(best)
    return len(starts), hits


def _bases(
    frame: Frame, first: int, last: int, window: tuple[int, int]
) -> tuple[int, int]:
    start, end = window
    if frame.strand == "+":
        return start + frame.offset + 3 * first, start + frame.offset + 3 * last - 1
    return end - frame.offset - 3 * last + 1, end - frame.offset - 3 * first


def _located(
    windows: int, hits: list[_Hit], dna: str, bounds: tuple[int, int]
) -> Located:
    bases = [_bases(h.frame, h.at, h.at + WINDOW, bounds) for h in hits]
    return Located(
        windows=windows,
        found=len(bases),
        span=(min(b[0] for b in bases), max(b[1] for b in bases)) if bases else None,
        ns=dna.upper().count("N"),
    )


def locate_protein(
    protein: str, window: str, window_start: int, code: GeneticCode
) -> Located:
    windows, hits = _hits(protein, six_frames(window, code))
    return _located(
        windows, hits, window, (window_start, window_start + len(window) - 1)
    )


def _segments(
    frames: list[Frame], span: tuple[int, int], bounds: tuple[int, int]
) -> list[str]:
    parts: list[str] = []
    for frame in frames:
        at = 0
        for part in frame.protein.split("*"):
            low, high = _bases(frame, at, at + len(part), bounds)
            if part and high >= span[0] and low <= span[1]:
                parts.append(part)
            at += len(part) + 1
    return sorted(parts, key=len, reverse=True)


def _open_frame(protein: str, parts: list[str]) -> OpenFrame | None:
    matcher = difflib.SequenceMatcher(None, autojunk=False)
    matcher.set_seq2(protein)
    best: OpenFrame | None = None
    for part in parts:
        if best is not None and len(part) <= best.identical:
            break
        matcher.set_seq1(part)
        same = sum(block.size for block in matcher.get_matching_blocks())
        if best is None or same > best.identical:
            best = OpenFrame(length=len(part), identical=same)
    return best


def _stops(protein: str, hits: list[_Hit]) -> tuple[list[int], bool]:
    frames = Counter((hit.frame.strand, hit.frame.offset) for hit in hits)
    held = max(frames, key=frames.__getitem__)
    in_frame = [h for h in hits if (h.frame.strand, h.frame.offset) == held]
    translated = in_frame[0].frame.protein
    shifts = sorted(hit.shift for hit in in_frame)
    whole = translated[max(0, shifts[0]) : shifts[-1] + len(protein)]
    first = min(hit.at for hit in in_frame)
    last = max(hit.at for hit in in_frame) + WINDOW
    stops = [
        at - min(in_frame, key=lambda hit: abs(hit.at - at)).shift + 1
        for at in range(first, last)
        if translated[at] == "*"
    ]
    return stops, len(frames) == 1 and "*" not in whole


def scan_for_protein(
    protein: str, window: str, window_start: int, code: GeneticCode
) -> MissingScan:
    frames = six_frames(window, code)
    bounds = (window_start, window_start + len(window) - 1)
    windows, hits = _hits(protein, frames)
    located = _located(windows, hits, window, bounds)
    if located.span is None:
        return MissingScan(
            located=located, open_frame=None, stops=[], intact_frame=None
        )
    stops, intact = _stops(protein, hits)
    return MissingScan(
        located=located,
        open_frame=_open_frame(protein, _segments(frames, located.span, bounds)),
        stops=stops,
        intact_frame=intact,
    )


def missing_verdict(located: Located, overlapping: list[GeneRow]) -> MissingVerdict:
    share = located.found / located.windows
    if share >= IN_DNA_SHARE:
        return "IN_DNA_OTHER_MODEL" if overlapping else "IN_DNA_UNANNOTATED"
    if located.ns > GAP_NS:
        return "GAP"
    if share >= MISSING:
        return "PARTIAL"
    return "NOT_IN_DNA"

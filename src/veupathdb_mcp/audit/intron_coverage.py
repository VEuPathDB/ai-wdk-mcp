"""The RNA-seq depth over a gene's introns, from the stranded coverage experiment of
its organism that covers the most bases, chosen once per organism."""

from __future__ import annotations

import re
import statistics
import weakref
from time import monotonic
from typing import Literal

from pydantic import BaseModel, ConfigDict
from veupathdb.jbrowse import (
    BIGWIG_MAX_BLOCKS,
    BIGWIG_MAX_RTREE_DEPTH,
    BigWigReader,
    BigWigSummary,
    JBrowseClient,
    SubTrack,
    TrackConfig,
)

from veupathdb_mcp.audit.introns import IntronDepth, Span, Strand, intron_key
from veupathdb_mcp.audit.track_reads import (
    READ_FAILURES,
    GeneSite,
    OrganismReads,
    failed_read,
)

COVERAGE_HEADERS_READ = 200
COVERAGE_CANDIDATE_PAIRS = 3
BIGWIG_READS_PER_DEPTH = 1 + BIGWIG_MAX_RTREE_DEPTH + BIGWIG_MAX_BLOCKS
NO_READS_OVER_GENE = "no shortlisted RNA-seq experiment has reads over this gene"
STRAND_WORDS: dict[Strand, tuple[str, ...]] = {
    "+": ("forward", "plus", "(+)"),
    "-": ("reverse", "minus", "(-)"),
}
UNREAD_STRAND_WORDS = ("sense", "antisense")
UNIFIED_TRACK = "unified"
TRACK_LIST_TRIES = 2
TRACK_LIST_RETRY_SECONDS = 600

type SubTrackStrand = Strand | Literal["unread"] | None

_BIGWIGS: weakref.WeakKeyDictionary[JBrowseClient, dict[str, BigWigReader]] = (
    weakref.WeakKeyDictionary()
)
_REFUSED_LISTS: weakref.WeakKeyDictionary[JBrowseClient, dict[str, _Refusals]] = (
    weakref.WeakKeyDictionary()
)


def _bigwig(client: JBrowseClient, path: str) -> BigWigReader:
    readers = _BIGWIGS.setdefault(client, {})
    if path not in readers:
        readers[path] = BigWigReader(client, path)
    return readers[path]


def _words(words: tuple[str, ...]) -> re.Pattern[str]:
    named = "|".join(re.escape(word) for word in words)
    return re.compile(rf"(?<!\w)(?:{named})(?!\w)")


_UNREAD_PATTERN = _words(UNREAD_STRAND_WORDS)
_STRAND_PATTERNS = {strand: _words(words) for strand, words in STRAND_WORDS.items()}


def strand_of(subtrack: SubTrack) -> SubTrackStrand:
    name = subtrack.name.lower()
    if _UNREAD_PATTERN.search(name):
        return "unread"
    for strand, pattern in _STRAND_PATTERNS.items():
        if pattern.search(name):
            return strand
    return None


def _stem(subtrack: SubTrack) -> str:
    name = subtrack.name.lower()
    for pattern in _STRAND_PATTERNS.values():
        name = pattern.sub("", name)
    return name


def _ordered(tracks: list[TrackConfig]) -> list[TrackConfig]:
    return sorted(tracks, key=lambda track: (track.label, track.key))


def stranded_pairs(tracks: list[TrackConfig]) -> list[tuple[SubTrack, SubTrack]]:
    pairs: dict[tuple[str, str], tuple[SubTrack, SubTrack]] = {}
    for track in _ordered(tracks):
        by_stem: dict[str, dict[SubTrackStrand, SubTrack]] = {}
        for sub in track.subtracks():
            if (strand := strand_of(sub)) in STRAND_WORDS:
                by_stem.setdefault(_stem(sub), {}).setdefault(strand, sub)
        for both in by_stem.values():
            if "+" in both and "-" in both:
                pair = (both["+"], both["-"])
                pairs.setdefault((pair[0].data_path, pair[1].data_path), pair)
    return list(pairs.values())


def unstranded_candidate(tracks: list[TrackConfig]) -> list[SubTrack]:
    unstranded = [
        (track, sub)
        for track in _ordered(tracks)
        for sub in track.subtracks()
        if strand_of(sub) is None
    ]
    unified = [
        sub
        for track, sub in unstranded
        if UNIFIED_TRACK in f"{track.key} {track.label}".lower()
    ]
    return (unified or [sub for _, sub in unstranded])[:1]


class CoverageChoice(BaseModel):
    model_config = ConfigDict(frozen=True)

    candidates: list[SubTrack]
    notes: list[str]


_CHOICES = OrganismReads[CoverageChoice]()


class DepthRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    depth: dict[str, IntronDepth] | None
    notes: list[str]


class _Measured(BaseModel):
    model_config = ConfigDict(frozen=True)

    track: str
    exon_median: float
    depths: list[float]


def _positions(spans: list[Span], first: int, last: int) -> list[int]:
    return [p for a, b in spans for p in range(max(a, first), min(b, last) + 1)]


class _Header(BaseModel):
    model_config = ConfigDict(frozen=True)

    path: str
    summary: BigWigSummary | None
    failure: str | None = None


async def _header(client: JBrowseClient, path: str) -> _Header:
    try:
        return _Header(path=path, summary=await _bigwig(client, path).summary())
    except READ_FAILURES as exc:
        return _Header(
            path=path, summary=None, failure=failed_read(f"header read of {path}", exc)
        )


def _breadth(found: list[BigWigSummary | None]) -> tuple[int, float] | None:
    summaries = [summary for summary in found if summary is not None]
    if len(summaries) != len(found):
        return None
    return (
        sum(summary.bases_covered for summary in summaries),
        sum(summary.sum_data for summary in summaries),
    )


class _Refusals(BaseModel):
    model_config = ConfigDict(frozen=True)

    count: int
    last: float


async def _tracks(client: JBrowseClient, abbrev: str) -> list[TrackConfig]:
    try:
        return await client.coverage_tracks(abbrev)
    except READ_FAILURES:
        refusals = _REFUSED_LISTS.setdefault(client, {})
        count = refusals[abbrev].count if abbrev in refusals else 0
        refusals[abbrev] = _Refusals(count=count + 1, last=monotonic())
        raise


def _cooling(client: JBrowseClient, abbrev: str) -> str | None:
    refusals = _REFUSED_LISTS.setdefault(client, {})
    if abbrev not in refusals or refusals[abbrev].count < TRACK_LIST_TRIES:
        return None
    left = refusals[abbrev].last + TRACK_LIST_RETRY_SECONDS - monotonic()
    if left <= 0:
        del refusals[abbrev]
        return None
    return (
        f"the RNA-seq track list of {abbrev} failed {TRACK_LIST_TRIES} times; "
        f"it is read again in {left:.0f} seconds"
    )


async def _choose(client: JBrowseClient, abbrev: str) -> CoverageChoice:
    tracks = await _tracks(client, abbrev)
    pairs = stranded_pairs(tracks)
    if not pairs:
        return CoverageChoice(candidates=unstranded_candidate(tracks), notes=[])
    files = list(dict.fromkeys(sub.data_path for pair in pairs for sub in pair))
    read = files[:COVERAGE_HEADERS_READ]
    headers = [await _header(client, path) for path in read]
    bounded = (
        f"{abbrev} lists {len(files)} stranded coverage files; the first "
        f"{len(read)} in label order were measured"
    )
    notes = [bounded] if len(files) > len(read) else []
    notes += [header.failure for header in headers if header.failure]
    summaries = {
        header.path: header.summary for header in headers if header.failure is None
    }
    ranked = [
        (breadth, pair)
        for pair in pairs
        if all(sub.data_path in summaries for sub in pair)
        and (breadth := _breadth([summaries[sub.data_path] for sub in pair]))
        is not None
    ]
    if not ranked:
        return CoverageChoice(
            candidates=[],
            notes=[*notes, f"no stranded coverage file of {abbrev} served a summary"],
        )
    shortlist = sorted(ranked, key=lambda found: found[0], reverse=True)
    return CoverageChoice(
        candidates=[
            sub for _, pair in shortlist[:COVERAGE_CANDIDATE_PAIRS] for sub in pair
        ],
        notes=notes,
    )


async def coverage_choice(client: JBrowseClient, abbrev: str) -> CoverageChoice:
    if (cooling := _cooling(client, abbrev)) is not None:
        return CoverageChoice(candidates=[], notes=[cooling])
    try:
        return await _CHOICES.read(client, abbrev, lambda: _choose(client, abbrev))
    except READ_FAILURES as exc:
        return CoverageChoice(
            candidates=[], notes=[failed_read("RNA-seq track list read", exc)]
        )


class _DepthTry(BaseModel):
    model_config = ConfigDict(frozen=True)

    measured: _Measured | None
    failure: str | None = None


async def _measured(
    client: JBrowseClient, sub: SubTrack, gene: GeneSite, exons: list[Span]
) -> _DepthTry:
    try:
        depths = await _bigwig(client, sub.data_path).depth(
            gene.seqid, gene.start, gene.end
        )
    except READ_FAILURES as exc:
        return _DepthTry(
            measured=None, failure=failed_read(f"depth read of {sub.name}", exc)
        )
    covered = [depths[p - gene.start] for p in _positions(exons, gene.start, gene.end)]
    return _DepthTry(
        measured=_Measured(
            track=sub.name,
            exon_median=statistics.median(covered) if covered else 0.0,
            depths=depths,
        )
    )


async def read_depth(
    client: JBrowseClient, gene: GeneSite, exons: list[Span], introns: list[Span]
) -> DepthRead:
    choice = await coverage_choice(client, gene.abbrev)
    if not choice.candidates:
        reason = f"{gene.abbrev} lists no RNA-seq coverage track"
        return DepthRead(depth=None, notes=choice.notes or [reason])
    found = [await _measured(client, sub, gene, exons) for sub in choice.candidates]
    read = [one.measured for one in found if one.measured is not None]
    notes = [*choice.notes, *(one.failure for one in found if one.failure)]
    if not read:
        names = ", ".join(sub.name for sub in choice.candidates)
        reason = (
            f"no coverage track read {gene.seqid}:{gene.start}-{gene.end} ({names})"
        )
        return DepthRead(depth=None, notes=[*notes, reason])
    best = max(read, key=lambda m: m.exon_median)
    if best.exon_median == 0:
        return DepthRead(depth=None, notes=[*notes, NO_READS_OVER_GENE])
    return DepthRead(
        depth={
            intron_key(intron): _intron_depth(best, gene, intron)
            for intron in introns
            if gene.start <= intron[0] <= intron[1] <= gene.end
        },
        notes=notes,
    )


def _intron_depth(best: _Measured, gene: GeneSite, intron: Span) -> IntronDepth:
    depths = [
        best.depths[p - gene.start] for p in _positions([intron], gene.start, gene.end)
    ]
    return IntronDepth(
        intron_median_depth=statistics.median(depths),
        exon_median_depth=best.exon_median,
        covered_share=round(sum(d > 0 for d in depths) / len(depths), 3),
        track=best.track,
    )

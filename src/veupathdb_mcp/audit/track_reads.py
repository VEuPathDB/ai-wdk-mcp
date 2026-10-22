"""The organism track lists and readers the audit checks share, read once per
organism and JBrowse client, and the reason a refused store read is unread."""

from __future__ import annotations

import asyncio
import weakref
from collections.abc import Awaitable, Callable

import httpx
from pydantic import BaseModel, ConfigDict
from veupathdb.errors import VEuPathDBError
from veupathdb.jbrowse import (
    GenomeIndexError,
    GenomeReader,
    JBrowseClient,
    JBrowseError,
    TabixReader,
    TrackConfig,
    TrackList,
    TrackReadError,
)

from veupathdb_mcp.audit.introns import Span, Strand

READ_FAILURES = (JBrowseError, TrackReadError, GenomeIndexError, httpx.HTTPError)

type ReadFailure = JBrowseError | TrackReadError | GenomeIndexError | httpx.HTTPError


class GeneSite(BaseModel):
    model_config = ConfigDict(frozen=True)

    abbrev: str
    seqid: str
    start: int
    end: int
    strand: Strand
    window: Span


_TABIX: weakref.WeakKeyDictionary[JBrowseClient, TabixReader] = (
    weakref.WeakKeyDictionary()
)
_GENOMES: weakref.WeakKeyDictionary[JBrowseClient, GenomeReader] = (
    weakref.WeakKeyDictionary()
)


class OrganismReads[T]:
    def __init__(self) -> None:
        self._done: weakref.WeakKeyDictionary[JBrowseClient, dict[str, T]] = (
            weakref.WeakKeyDictionary()
        )
        self._running: weakref.WeakKeyDictionary[
            asyncio.AbstractEventLoop, dict[tuple[int, str], asyncio.Future[T]]
        ] = weakref.WeakKeyDictionary()

    async def read(
        self, client: JBrowseClient, abbrev: str, read: Callable[[], Awaitable[T]]
    ) -> T:
        done = self._done.setdefault(client, {})
        if abbrev in done:
            return done[abbrev]
        running = self._running.setdefault(asyncio.get_running_loop(), {})
        key = (id(client), abbrev)
        if key not in running:
            running[key] = asyncio.ensure_future(read())
        try:
            found = await running[key]
        finally:
            running.pop(key, None)
        done[abbrev] = found
        return found


_ORGANISM_TRACKS = OrganismReads[TrackList]()


def tabix_reader(client: JBrowseClient) -> TabixReader:
    if client not in _TABIX:
        _TABIX[client] = TabixReader(client)
    return _TABIX[client]


def genome_reader(client: JBrowseClient) -> GenomeReader:
    if client not in _GENOMES:
        _GENOMES[client] = GenomeReader(client)
    return _GENOMES[client]


def failed_read(reads: str, exc: ReadFailure) -> str:
    match exc:
        case VEuPathDBError():
            return f"the {reads} failed: {exc.detail or exc.title}"
        case httpx.HTTPError():
            return f"the {reads} failed: {type(exc).__name__} {exc}"


async def organism_tracks(client: JBrowseClient, abbrev: str) -> TrackList:
    return await _ORGANISM_TRACKS.read(
        client, abbrev, lambda: client.track_list("organismSpecific", abbrev)
    )


def tabix_track(listed: TrackList, path: str) -> TrackConfig | None:
    return next(
        (
            track
            for track in listed.tracks
            if path in track.data_path and track.reads_with_tabix
        ),
        None,
    )

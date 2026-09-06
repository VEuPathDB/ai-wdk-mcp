"""A gene search answers while the vector index's database is unreachable.

The catalog is searches, parameters and organisms. The semantic index is a
separate store, and the site whose organisms a gene search needs is served
whether or not that store answers.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Coroutine
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from asyncpg.exceptions import InvalidAuthorizationSpecificationError
from sqlalchemy.ext.asyncio import AsyncSession
from veupathdb.domain.parameters.wdk_vocab import (
    WDKTreeBoxVocabNode,
    WDKVocabNodeData,
)
from veupathdb.wdk.wdk_models import (
    StepValidation,
    WDKRecordType,
    WDKSearch,
    WDKSearchResponse,
)
from veupathdb.wdk.wdk_parameters import WDKEnumParam

from veupathdb_mcp.catalog import discovery_service
from veupathdb_mcp.catalog.discovery import CatalogPolicy
from veupathdb_mcp.catalog.discovery_service import DiscoveryService
from veupathdb_mcp.catalog.disk_cache import (
    SNAPSHOT_FORMAT_VERSION,
    CatalogSnapshot,
    save_catalog_cache,
)
from veupathdb_mcp.embeddings import record_manager
from veupathdb_mcp.gene_lookup import organisms
from veupathdb_mcp.gene_lookup.organisms import (
    ORGANISM_PARAM,
    TAXON_SEARCH,
    list_organisms,
)

SITE = "plasmodb"
RECORD_TYPE = "transcript"
SITE_ORGANISMS = ["Plasmodium berghei ANKA", "Plasmodium falciparum 3D7"]

# Nothing listens here, so the first statement of an index sync fails to connect.
CLOSED_PORT_DSN = "postgresql+asyncpg://nobody:nothing@127.0.0.1:1/none"

_MEGABYTE = 1024 * 1024


def _taxon_search() -> WDKSearch:
    return WDKSearch(
        url_segment=TAXON_SEARCH,
        display_name="Sequences by taxon",
        summary="Every sequence of one taxon",
    )


def _taxon_details() -> WDKSearchResponse:
    tree = WDKTreeBoxVocabNode(
        data=WDKVocabNodeData(term="root", display="root"),
        children=[
            WDKTreeBoxVocabNode(data=WDKVocabNodeData(term=name, display=name))
            for name in SITE_ORGANISMS
        ],
    )
    return WDKSearchResponse(
        search_data=WDKSearch(
            url_segment=TAXON_SEARCH,
            display_name="Sequences by taxon",
            parameters=[
                WDKEnumParam(
                    name=ORGANISM_PARAM,
                    display_name="Organism",
                    type="multi-pick-vocabulary",
                    display_type="treeBox",
                    vocabulary=tree,
                ),
            ],
        ),
        validation=StepValidation(level="SEMANTIC", is_valid=True),
    )


class _Client:
    async def get_search_details(
        self, record_type: str, search_name: str, *, expand_params: bool = True
    ) -> WDKSearchResponse:
        del expand_params
        assert record_type == RECORD_TYPE
        assert search_name == TAXON_SEARCH
        return _taxon_details()


class _Router:
    def get_client(self, site_id: str) -> _Client:
        del site_id
        return _Client()


def _write_snapshot(cache_dir: Path) -> None:
    save_catalog_cache(
        SITE,
        CatalogSnapshot(
            format_version=SNAPSHOT_FORMAT_VERSION,
            record_types=[WDKRecordType(url_segment=RECORD_TYPE, display_name="Gene")],
            searches={RECORD_TYPE: [_taxon_search()]},
            dataset_summaries={},
            dataset_contacts={},
            search_categories={},
            search_category_labels={},
            available_categories=[],
        ),
        cache_dir,
    )


@dataclass
class _UnreachableIndex:
    """The service under test and the background work its load started."""

    service: DiscoveryService
    spawned: list[asyncio.Task[None]]


@pytest.fixture
def unreachable_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> _UnreachableIndex:
    """A discovery service whose index sync can only fail, wired to gene lookup."""
    monkeypatch.setenv("DATABASE_URL", CLOSED_PORT_DSN)
    monkeypatch.setenv("EMBEDDING_INDEX_SYNC_ENABLED", "true")
    _write_snapshot(tmp_path)

    spawned: list[asyncio.Task[None]] = []

    def spawn(
        coro: Coroutine[Any, Any, None], /, *, name: str | None = None
    ) -> asyncio.Task[None]:
        task = asyncio.create_task(coro, name=name)
        spawned.append(task)
        return task

    service = DiscoveryService(
        cache_dir=tmp_path,
        budget_bytes=64 * _MEGABYTE,
        policy=CatalogPolicy(refresh=False, sync=True),
        spawn=spawn,
    )

    def router() -> _Router:
        return _Router()

    def discovery() -> DiscoveryService:
        return service

    monkeypatch.setattr(discovery_service, "get_site_router", router)
    monkeypatch.setattr(organisms, "get_discovery_service", discovery)
    return _UnreachableIndex(service=service, spawned=spawned)


async def test_the_site_organisms_are_served_while_the_index_store_is_down(
    unreachable_index: _UnreachableIndex,
) -> None:
    assert await list_organisms(SITE) == SITE_ORGANISMS


async def test_the_failing_sync_is_a_separate_step_that_swallows_its_own_failure(
    unreachable_index: _UnreachableIndex,
) -> None:
    await list_organisms(SITE)

    assert [task.get_name() for task in unreachable_index.spawned] == [
        f"index-sync-{SITE}"
    ]
    assert await asyncio.gather(*unreachable_index.spawned) == [None]


async def test_the_catalog_still_offers_the_index_it_could_not_sync(
    unreachable_index: _UnreachableIndex,
) -> None:
    await list_organisms(SITE)
    catalog = await unreachable_index.service.get_catalog(SITE)

    index = catalog.get_semantic_index()
    assert index is not None
    assert [entry.search_name for entry in index.entries] == [TAXON_SEARCH]


async def test_a_store_that_refuses_this_process_does_not_reach_the_gene_search(
    unreachable_index: _UnreachableIndex, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A Postgres refusal is an ``asyncpg`` error, and no relation of OSError."""

    refusal = InvalidAuthorizationSpecificationError('role "postgres" does not exist')

    @asynccontextmanager
    async def refused() -> AsyncIterator[AsyncSession]:
        raise refusal
        yield  # pragma: no cover

    monkeypatch.setattr(record_manager, "embedding_session", refused)

    assert await list_organisms(SITE) == SITE_ORGANISMS
    assert await asyncio.gather(*unreachable_index.spawned) == [None]

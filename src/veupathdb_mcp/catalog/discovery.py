"""Cached catalog of searches, parameters, and metadata for one site."""

import asyncio
from collections.abc import Coroutine, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from veupathdb.errors import VEuPathDBError
from veupathdb.logging import get_logger
from veupathdb.wdk.client import VEuPathDBClient
from veupathdb.wdk.wdk_models import (
    WDKRecordType,
    WDKSearch,
    WDKSearchResponse,
)

from veupathdb_mcp.catalog.catalog_metadata import (
    load_dataset_metadata,
    load_ontology_categories,
    load_searches_for_rt,
    process_record_type_entry,
)
from veupathdb_mcp.catalog.disk_cache import (
    CatalogSnapshot,
    save_catalog_cache,
    try_load_catalog_cache,
)
from veupathdb_mcp.embeddings.errors import SemanticIndexUnavailableError
from veupathdb_mcp.embeddings.semantic_index import SemanticSearchIndex

logger = get_logger(__name__)

# A cold build fetches a whole catalog. The allocations of concurrent builds
# sum, so a process builds one at a time.
_CATALOG_BUILD = asyncio.Semaphore(1)

# A loaded catalog holds about four times its serialized length, measured on a
# warm site. The floor covers a catalog whose snapshot is not yet known.
_RESIDENT_PER_PAYLOAD_BYTE = 4
_EMPTY_CATALOG_BYTES = 1024 * 1024


@dataclass(frozen=True, slots=True)
class CatalogPolicy:
    """What this process may do with a catalog it did not build."""

    refresh: bool = True
    sync: bool = True


class TaskSpawner(Protocol):
    """Schedules a coroutine on the running loop."""

    def __call__(
        self, coro: Coroutine[Any, Any, None], /, *, name: str | None = None
    ) -> object: ...


class SearchCatalog:
    """Cached catalog of searches for a site."""

    def __init__(
        self,
        site_id: str,
        *,
        cache_dir: Path,
        policy: CatalogPolicy,
        spawn: TaskSpawner,
    ) -> None:
        self.site_id = site_id
        self._cache_dir = cache_dir
        self._policy = policy
        self._spawn = spawn
        self._refresh: object | None = None
        self._index_sync: object | None = None
        self._record_types: list[WDKRecordType] = []
        self._searches: dict[str, list[WDKSearch]] = {}
        self._search_details: dict[str, WDKSearchResponse] = {}
        self._dataset_summaries: dict[str, str] = {}
        self._dataset_contacts: dict[str, str] = {}
        self._semantic_index: SemanticSearchIndex | None = None
        self._search_categories: dict[str, str] = {}
        self._search_category_labels: dict[str, str] = {}
        self._available_categories: set[str] = set()
        self._payload_bytes = 0

    @property
    def memory_bytes(self) -> int:
        """Accounted resident cost of this catalog, for the eviction budget.

        The vectors live in Postgres, so a catalog costs what its snapshot does.
        """
        return _EMPTY_CATALOG_BYTES + self._payload_bytes * _RESIDENT_PER_PAYLOAD_BYTE

    # ------------------------------------------------------------------
    # Snapshot helpers
    # ------------------------------------------------------------------

    def _restore_from_snapshot(self, snapshot: CatalogSnapshot) -> None:
        """Populate in-memory state from a cached snapshot."""
        self._record_types = snapshot.record_types
        self._searches = snapshot.searches
        self._dataset_summaries = snapshot.dataset_summaries
        self._dataset_contacts = snapshot.dataset_contacts
        self._search_categories = snapshot.search_categories
        self._search_category_labels = snapshot.search_category_labels
        self._available_categories = set(snapshot.available_categories)
        self._payload_bytes = snapshot.payload_bytes

    def _to_snapshot(self) -> CatalogSnapshot:
        """Capture current in-memory state as a serializable snapshot."""
        return CatalogSnapshot(
            record_types=self._record_types,
            searches=self._searches,
            dataset_summaries=self._dataset_summaries,
            dataset_contacts=self._dataset_contacts,
            search_categories=self._search_categories,
            search_category_labels=self._search_category_labels,
            available_categories=sorted(self._available_categories),
        )

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    async def _fetch_from_api(self, client: VEuPathDBClient) -> None:
        """Fetch catalog data from the live WDK API and save to disk cache."""
        async with _CATALOG_BUILD:
            record_types = await client.get_record_types(expanded=True)
            expanded_supported = any(rt.searches is not None for rt in record_types)

            self._record_types = []
            self._searches = {}
            await self._populate_from_record_types(
                client, record_types, expanded_supported=expanded_supported
            )

            ds = await load_dataset_metadata(client, self.site_id)
            self._dataset_summaries = ds.summaries
            self._dataset_contacts = ds.contacts

            onto = await load_ontology_categories(client, self.site_id)
            self._search_categories = onto.search_categories
            self._search_category_labels = onto.search_category_labels
            self._available_categories = onto.available_categories

            self._collect_semantic_index()
            snapshot = self._to_snapshot()
            save_catalog_cache(self.site_id, snapshot, self._cache_dir)
            self._payload_bytes = snapshot.payload_bytes

    async def load(self, client: VEuPathDBClient) -> None:
        """Load the catalog from the disk cache, or from the API on a miss.

        A stale cache is served at once and refreshed in the background. One
        load per site is the caller's invariant.
        """
        snapshot = try_load_catalog_cache(self.site_id, self._cache_dir)

        if snapshot is not None:
            self._restore_from_snapshot(snapshot)
            self._collect_semantic_index()

            if snapshot.is_stale and not self._policy.refresh:
                logger.info(
                    "Search catalog restored from stale cache; this process serves it "
                    "and does not rebuild",
                    site_id=self.site_id,
                )
            elif snapshot.is_stale:
                logger.info(
                    "Search catalog restored from stale cache, refreshing in background",
                    site_id=self.site_id,
                )
                self._refresh = self._spawn(
                    self._background_refresh(client),
                    name=f"catalog-refresh-{self.site_id}",
                )
            else:
                logger.info(
                    "Search catalog restored from cache",
                    site_id=self.site_id,
                    record_types=len(self._record_types),
                    total_searches=sum(len(s) for s in self._searches.values()),
                )
            return

        logger.info("Loading search catalog from API", site_id=self.site_id)
        try:
            await self._fetch_from_api(client)
            logger.info(
                "Search catalog loaded from API and cached",
                site_id=self.site_id,
                record_types=len(self._record_types),
                total_searches=sum(len(s) for s in self._searches.values()),
                datasets=len(self._dataset_summaries),
            )
        except (VEuPathDBError, OSError, RuntimeError) as e:
            logger.exception(
                "Failed to load catalog", site_id=self.site_id, error=str(e)
            )
            raise

    async def _background_refresh(self, client: VEuPathDBClient) -> None:
        """Re-fetch catalog from the API in the background, replacing in-memory state."""
        try:
            await self._fetch_from_api(client)
            logger.info(
                "Search catalog background refresh complete",
                site_id=self.site_id,
                record_types=len(self._record_types),
                total_searches=sum(len(s) for s in self._searches.values()),
            )
        except VEuPathDBError, OSError, RuntimeError:
            logger.warning(
                "Background catalog refresh failed (serving stale cache)",
                site_id=self.site_id,
                exc_info=True,
            )

    def _collect_semantic_index(self) -> None:
        """Hold the index the catalog offers, and start the sync beside it.

        The store is a separate service. The catalog is served whether or not
        it answers, so the sync is neither awaited nor allowed to fail a load.
        """
        index = SemanticSearchIndex(site_id=self.site_id)
        index.collect(self._searches, category_labels=self._search_category_labels)
        self._semantic_index = index
        if self._policy.sync and index.entries:
            self._index_sync = self._spawn(
                self._sync_semantic_index(index),
                name=f"index-sync-{self.site_id}",
            )

    async def _sync_semantic_index(self, index: SemanticSearchIndex) -> None:
        """Write the index to its store, reporting a refusal rather than raising."""
        try:
            await index.sync()
        except SemanticIndexUnavailableError as exc:
            logger.warning(
                "The semantic index was not synced, so ranking stays lexical",
                site_id=self.site_id,
                error_class=type(exc.__cause__ or exc).__name__,
                error=str(exc),
            )

    # ------------------------------------------------------------------
    # Record type / search population
    # ------------------------------------------------------------------

    async def _populate_from_record_types(
        self,
        client: VEuPathDBClient,
        record_types: Sequence[WDKRecordType],
        *,
        expanded_supported: bool,
    ) -> None:
        """Populate internal caches from the record types array."""
        for rt in record_types:
            result = process_record_type_entry(
                rt, expanded_supported=expanded_supported
            )
            if result is None:
                continue

            typed_rt, searches = result
            rt_name = typed_rt.url_segment
            self._record_types.append(typed_rt)

            if searches is not None and len(searches) > 0:
                self._searches[rt_name] = searches
            else:
                fetched = await load_searches_for_rt(client, rt_name)
                if fetched is not None:
                    self._searches[rt_name] = fetched

    # ------------------------------------------------------------------
    # Public query API
    # ------------------------------------------------------------------

    def get_record_types(self) -> list[WDKRecordType]:
        """Get all record types."""
        return self._record_types

    def get_searches(self, record_type: str) -> list[WDKSearch]:
        """Get searches for a record type."""
        return self._searches.get(record_type, [])

    def get_semantic_index(self) -> SemanticSearchIndex | None:
        """Get the semantic search index, or None if not available."""
        return self._semantic_index

    def find_search(self, record_type: str, search_name: str) -> WDKSearch | None:
        """Find a specific search."""
        for search in self.get_searches(record_type):
            if search.url_segment == search_name:
                return search
        return None

    def find_record_type_for_search(self, search_name: str) -> str | None:
        """Find which record type owns a search.

        Mirrors WDK's ``WdkModel.getQuestionByName()``.
        """
        for rt_name, searches in self._searches.items():
            if any(s.url_segment == search_name for s in searches):
                return rt_name
        return None

    def get_search_category(self, search_name: str) -> str | None:
        """Get the ontology subcategory for a search, or None if universal."""
        return self._search_categories.get(search_name)

    async def get_search_details(
        self,
        client: VEuPathDBClient,
        record_type: str,
        search_name: str,
        *,
        expand_params: bool = True,
    ) -> WDKSearchResponse:
        """Get detailed search config with caching."""
        cache_key = f"{record_type}/{search_name}?expand={int(expand_params)}"
        if cache_key not in self._search_details:
            details = await client.get_search_details(
                record_type, search_name, expand_params=expand_params
            )
            self._search_details[cache_key] = details
        return self._search_details[cache_key]

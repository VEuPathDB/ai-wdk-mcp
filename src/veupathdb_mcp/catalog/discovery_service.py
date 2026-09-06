"""Global DiscoveryService: manages per-site SearchCatalog instances."""

import asyncio
import threading
from pathlib import Path
from typing import Protocol

from cachetools import LRUCache
from veupathdb.domain.search import SearchContext
from veupathdb.errors import VEuPathDBError
from veupathdb.logging import get_logger
from veupathdb.wdk.site_router import get_site_router
from veupathdb.wdk.wdk_models import (
    WDKRecordType,
    WDKSearch,
    WDKSearchResponse,
)

from veupathdb_mcp.catalog.discovery import (
    CatalogPolicy,
    SearchCatalog,
    TaskSpawner,
)
from veupathdb_mcp.catalog.disk_cache import DEFAULT_CATALOG_CACHE_DIR
from veupathdb_mcp.locks import KeyedLock
from veupathdb_mcp.settings import get_mcp_settings

logger = get_logger(__name__)

_MEGABYTE = 1024 * 1024


class ReadinessSink(Protocol):
    """Where the warm-up reports the catalogs it loaded."""

    def register_catalog(self, site_id: str) -> None: ...

    def mark_catalog_ready(self, site_id: str) -> None: ...

    def mark_catalog_failed(self, site_id: str, error: str) -> None: ...


class DiscoveryService:
    """Service for discovering and caching site metadata.

    The catalogs are held under a memory budget and the least recently used
    site leaves when the budget is reached, so the process does not grow with
    the number of sites a session touches.
    """

    def __init__(
        self,
        *,
        cache_dir: Path,
        budget_bytes: int,
        policy: CatalogPolicy,
        spawn: TaskSpawner,
    ) -> None:
        self._cache_dir = cache_dir
        self._policy = policy
        self._spawn = spawn
        self._catalogs: LRUCache[str, SearchCatalog] = LRUCache(
            maxsize=budget_bytes, getsizeof=lambda catalog: catalog.memory_bytes
        )
        self._builds = KeyedLock()

    def held_sites(self) -> list[str]:
        """The sites this process currently holds."""
        return list(self._catalogs)

    def held_bytes(self) -> int:
        """Accounted bytes of the held catalogs."""
        return int(self._catalogs.currsize)

    async def get_catalog(self, site_id: str) -> SearchCatalog:
        """Get the site's catalog, building it if this process does not hold it."""
        async with self._builds(site_id):
            held: SearchCatalog | None = self._catalogs.get(site_id)
            if held is not None:
                return held

            catalog = SearchCatalog(
                site_id,
                cache_dir=self._cache_dir,
                policy=self._policy,
                spawn=self._spawn,
            )
            await catalog.load(get_site_router().get_client(site_id))
            self._hold(site_id, catalog)
            return catalog

    def _hold(self, site_id: str, catalog: SearchCatalog) -> None:
        """Admit a catalog, evicting least recently used sites for its room."""
        size = catalog.memory_bytes
        if size > self._catalogs.maxsize:
            logger.warning(
                "Site catalog is larger than the eviction budget, so it is rebuilt "
                "on every touch",
                site_id=site_id,
                catalog_bytes=size,
                budget_bytes=self._catalogs.maxsize,
            )
            return
        before = set(self._catalogs)
        self._catalogs[site_id] = catalog
        evicted = sorted(before - set(self._catalogs))
        if evicted:
            logger.info(
                "Site catalogs evicted to stay inside the budget",
                site_id=site_id,
                evicted=evicted,
                held_sites=self.held_sites(),
                held_bytes=self.held_bytes(),
            )

    async def get_record_types(self, site_id: str) -> list[WDKRecordType]:
        """Get record types for a site."""
        catalog = await self.get_catalog(site_id)
        return catalog.get_record_types()

    async def get_searches(self, site_id: str, record_type: str) -> list[WDKSearch]:
        """Get searches for a record type."""
        catalog = await self.get_catalog(site_id)
        return catalog.get_searches(record_type)

    async def get_search_details(
        self,
        ctx: SearchContext,
        *,
        expand_params: bool = True,
    ) -> WDKSearchResponse:
        """Get detailed search configuration."""
        catalog = await self.get_catalog(ctx.site_id)
        router = get_site_router()
        client = router.get_client(ctx.site_id)
        return await catalog.get_search_details(
            client,
            ctx.record_type,
            ctx.search_name,
            expand_params=expand_params,
        )

    async def preload_all(self, readiness: ReadinessSink) -> None:
        """Preload catalogs for every site, sequentially.

        All sites (component + portal) are awaited before returning, so
        ``/health/ready`` only reports healthy once every catalog is
        actually usable. The readiness state is updated per site so the
        endpoint can report *which* catalogs are still loading.
        """
        router = get_site_router()
        sites = router.list_sites()
        # Components first (fast), then portals (slow), so quick wins surface early.
        sites = sorted(sites, key=lambda s: (s.is_portal, s.id))
        for s in sites:
            readiness.register_catalog(s.id)

        for s in sites:
            try:
                logger.info("[warm-up] Preloading %s", s.id)
                await self.get_catalog(s.id)
                logger.info("[warm-up] Preloaded %s", s.id)
            except (VEuPathDBError, OSError, RuntimeError) as e:
                logger.warning("[warm-up] Failed %s: %s", s.id, e)
                readiness.mark_catalog_failed(s.id, str(e))
            else:
                readiness.mark_catalog_ready(s.id)


# ---------------------------------------------------------------------------
# Global singleton
# ---------------------------------------------------------------------------

_discovery_holder: dict[str, DiscoveryService] = {}
_discovery_lock = threading.Lock()


def _configured_service() -> DiscoveryService:
    """The service this process serves, from the settings in force."""
    settings = get_mcp_settings()
    return DiscoveryService(
        cache_dir=DEFAULT_CATALOG_CACHE_DIR,
        budget_bytes=settings.site_catalog_budget_mb * _MEGABYTE,
        policy=CatalogPolicy(
            refresh=settings.catalog_refresh_enabled,
            sync=settings.embedding_index_sync_enabled,
        ),
        spawn=asyncio.create_task,
    )


def get_discovery_service() -> DiscoveryService:
    """Get the global discovery service."""
    if "v" in _discovery_holder:
        return _discovery_holder["v"]
    with _discovery_lock:
        if "v" not in _discovery_holder:
            _discovery_holder["v"] = _configured_service()
        return _discovery_holder["v"]

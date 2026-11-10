from __future__ import annotations

from collections.abc import Coroutine
from pathlib import Path
from typing import Any

from veupathdb_mcp.catalog.discovery import CatalogPolicy, SearchCatalog
from veupathdb_mcp.catalog.disk_cache import CatalogSnapshot


def _never_spawned(coro: Coroutine[Any, Any, None], *, name: str | None = None) -> None:
    del name
    coro.close()


def offered_catalog(offered: list[str] | None = None) -> SearchCatalog:
    catalog = SearchCatalog(
        "testdb",
        cache_dir=Path("unwritten"),
        policy=CatalogPolicy(refresh=False, sync=False),
        spawn=_never_spawned,
    )
    catalog._restore_from_snapshot(
        CatalogSnapshot(
            record_types=[],
            searches={},
            datasets=[],
            search_categories={},
            available_categories=[],
            offered_searches=offered or [],
        )
    )
    return catalog

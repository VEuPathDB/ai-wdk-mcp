"""The catalogs a process holds are bounded by a memory budget.

Per-site catalogs and semantic indexes load on demand. Without a bound the
process grows with every site a session touches until the kernel kills it.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from veupathdb_mcp.catalog import discovery_service
from veupathdb_mcp.catalog.discovery import CatalogPolicy
from veupathdb_mcp.catalog.discovery_service import DiscoveryService
from veupathdb_mcp.settings import McpSettings

MIB = 1024 * 1024


def _service(budget_bytes: int) -> DiscoveryService:
    """A service with its host dependencies named."""
    return DiscoveryService(
        cache_dir=Path("/nonexistent"),
        budget_bytes=budget_bytes,
        policy=CatalogPolicy(),
        spawn=asyncio.create_task,
    )


@dataclass
class _Catalogs:
    """What the fake catalogs report, and what they recorded."""

    sizes: dict[str, int] = field(default_factory=dict)
    loads: list[str] = field(default_factory=list)
    gate: asyncio.Event | None = None
    entered: asyncio.Event | None = None


_state = _Catalogs()


class _FakeCatalog:
    """A catalog that records its loads and reports a fixed accounted size."""

    def __init__(self, site_id: str, **host: object) -> None:
        self.site_id = site_id
        self.host = host

    async def load(self, client: object) -> None:
        del client
        _state.loads.append(self.site_id)
        if _state.entered is not None:
            _state.entered.set()
        if _state.gate is not None:
            await _state.gate.wait()

    @property
    def memory_bytes(self) -> int:
        return _state.sizes.get(self.site_id, 10 * MIB)


class _FakeRouter:
    def get_client(self, site_id: str) -> str:
        return f"client-{site_id}"


@pytest.fixture(autouse=True)
def catalogs(monkeypatch: pytest.MonkeyPatch) -> _Catalogs:
    _state.sizes.clear()
    _state.loads.clear()
    _state.gate = None
    _state.entered = None
    monkeypatch.setattr(discovery_service, "SearchCatalog", _FakeCatalog)
    monkeypatch.setattr(discovery_service, "get_site_router", _FakeRouter)
    return _state


async def test_a_second_touch_of_a_held_site_does_not_reload_it(
    catalogs: _Catalogs,
) -> None:
    service = _service(100 * MIB)

    await service.get_catalog("plasmodb")
    await service.get_catalog("plasmodb")

    assert catalogs.loads == ["plasmodb"]


async def test_the_least_recently_used_site_leaves_when_the_budget_is_reached(
    catalogs: _Catalogs,
) -> None:
    catalogs.sizes.update({"a": 40 * MIB, "b": 40 * MIB, "c": 40 * MIB})
    service = _service(100 * MIB)

    await service.get_catalog("a")
    await service.get_catalog("b")
    await service.get_catalog("a")
    await service.get_catalog("c")

    assert service.held_sites() == ["a", "c"]


async def test_the_held_bytes_never_pass_the_budget(catalogs: _Catalogs) -> None:
    catalogs.sizes.update(dict.fromkeys(("a", "b", "c", "d", "e"), 30 * MIB))
    service = _service(100 * MIB)

    for name in ("a", "b", "c", "d", "e"):
        await service.get_catalog(name)

    assert service.held_bytes() <= 100 * MIB
    assert len(service.held_sites()) == 3


async def test_an_evicted_site_is_rebuilt_on_the_next_touch(
    catalogs: _Catalogs,
) -> None:
    catalogs.sizes.update({"a": 60 * MIB, "b": 60 * MIB})
    service = _service(100 * MIB)

    await service.get_catalog("a")
    await service.get_catalog("b")
    assert service.held_sites() == ["b"]

    await service.get_catalog("a")

    assert catalogs.loads == ["a", "b", "a"]


async def test_a_site_larger_than_the_budget_is_served_and_not_held(
    catalogs: _Catalogs,
) -> None:
    catalogs.sizes["huge"] = 200 * MIB
    service = _service(100 * MIB)

    catalog = await service.get_catalog("huge")

    assert catalog.site_id == "huge"
    assert service.held_sites() == []


async def test_two_callers_of_one_site_build_it_once(catalogs: _Catalogs) -> None:
    catalogs.gate = asyncio.Event()
    catalogs.entered = asyncio.Event()
    service = _service(100 * MIB)

    first = asyncio.create_task(service.get_catalog("plasmodb"))
    await catalogs.entered.wait()
    second = asyncio.create_task(service.get_catalog("plasmodb"))
    await asyncio.sleep(0)
    catalogs.gate.set()
    await asyncio.gather(first, second)

    assert catalogs.loads == ["plasmodb"]


def test_the_configured_service_reads_its_cache_directory_from_the_settings(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """CATALOG_CACHE_DIR names where snapshots are read and written."""
    settings = McpSettings(catalog_cache_dir=tmp_path / "snapshots")
    monkeypatch.setattr(discovery_service, "get_mcp_settings", lambda: settings)

    service = discovery_service._configured_service()

    assert service._cache_dir == tmp_path / "snapshots"


@pytest.mark.parametrize("refresh", [True, False])
@pytest.mark.parametrize("sync", [True, False])
def test_the_configured_service_takes_its_policy_from_the_settings(
    monkeypatch: pytest.MonkeyPatch,
    *,
    refresh: bool,
    sync: bool,
) -> None:
    """CATALOG_REFRESH_ENABLED and EMBEDDING_INDEX_SYNC_ENABLED reach the policy."""
    settings = McpSettings(
        catalog_refresh_enabled=refresh,
        embedding_index_sync_enabled=sync,
        site_catalog_budget_mb=7,
    )
    monkeypatch.setattr(discovery_service, "get_mcp_settings", lambda: settings)

    service = discovery_service._configured_service()

    assert service._policy == CatalogPolicy(refresh=refresh, sync=sync)
    assert service._catalogs.maxsize == 7 * MIB

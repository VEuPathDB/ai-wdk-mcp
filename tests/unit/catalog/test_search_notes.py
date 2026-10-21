"""A search the site publishes no description for carries a measured note."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from veupathdb.domain import SearchContext
from veupathdb.wdk import WDKSearch, WDKSearchResponse

from veupathdb_mcp.catalog import discovery_service, param_resolution, searches
from veupathdb_mcp.catalog.discovery import CatalogPolicy
from veupathdb_mcp.catalog.discovery_service import DiscoveryService
from veupathdb_mcp.catalog.disk_cache import CatalogSnapshot, save_catalog_cache
from veupathdb_mcp.catalog.param_resolution import get_search_parameters
from veupathdb_mcp.catalog.search_collection import collect_search_candidates
from veupathdb_mcp.catalog.search_notes import described
from veupathdb_mcp.tools.catalog_tools import get_search_overview

_SITE_DESCRIPTION = "Find groups by the number of taxa they hold."


def _single_copy(description: str = "") -> WDKSearch:
    return WDKSearch(
        url_segment="GroupsBySingleCopy",
        full_name="GroupQuestions.GroupsBySingleCopy",
        display_name="Single Copy Orthogroups",
        short_display_name="Single Copy Orthogroups",
        description=description,
        output_record_class_name="group",
        query_name="ByGenomeCount",
    )


def _single_copy_response() -> WDKSearchResponse:
    return WDKSearchResponse.model_validate(
        {
            "searchData": _single_copy().model_dump(by_alias=True),
            "validation": {"level": "DISPLAYABLE", "isValid": True},
        }
    )


def _holds_the_note(text: str) -> bool:
    return "same query as Number of Taxa" in text and "L=NT AND L=N" in text


def test_an_empty_description_takes_the_note() -> None:
    assert _holds_the_note(described("orthomcl", _single_copy()).description)


def test_a_published_description_stands() -> None:
    search = _single_copy(_SITE_DESCRIPTION)
    assert described("orthomcl", search).description == _SITE_DESCRIPTION


def test_the_same_search_on_another_site_takes_no_note() -> None:
    assert described("plasmodb", _single_copy()).description == ""


@pytest.fixture
def orthomcl(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> DiscoveryService:
    save_catalog_cache(
        "orthomcl",
        CatalogSnapshot(
            record_types=[],
            searches={"group": [_single_copy()]},
            datasets=[],
            search_categories={},
            available_categories=[],
        ),
        cache_dir=tmp_path,
    )
    monkeypatch.setattr(discovery_service, "get_site_router", MagicMock)
    return DiscoveryService(
        cache_dir=tmp_path,
        budget_bytes=1 << 30,
        policy=CatalogPolicy(refresh=False, sync=False),
        spawn=asyncio.create_task,
    )


async def test_the_listing_carries_the_note(orthomcl: DiscoveryService) -> None:
    (search,) = await orthomcl.get_searches("orthomcl", "group")
    assert _holds_the_note(search.description)


async def test_the_ranking_candidates_carry_the_note(
    orthomcl: DiscoveryService,
) -> None:
    ((search, _),) = await collect_search_candidates(orthomcl, "orthomcl", ["group"])
    assert _holds_the_note(search.description)


async def test_a_search_found_by_name_carries_the_note(
    orthomcl: DiscoveryService,
) -> None:
    catalog = await orthomcl.get_catalog("orthomcl")
    found = catalog.find_search("group", "GroupsBySingleCopy")
    assert found is not None
    assert _holds_the_note(found.description)


async def test_the_indexed_text_holds_the_note(orthomcl: DiscoveryService) -> None:
    catalog = await orthomcl.get_catalog("orthomcl")
    index = catalog.get_semantic_index()
    assert index is not None
    (entry,) = index.entries
    assert _holds_the_note(entry.enriched_text)


async def test_the_overview_description_is_the_note(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = MagicMock()
    client.get_search_details = AsyncMock(return_value=_single_copy_response())
    monkeypatch.setattr(searches, "get_wdk_client", lambda _site: client)

    overview = await get_search_overview("orthomcl", "GroupsBySingleCopy", "group")

    assert _holds_the_note(overview.description)


async def test_the_parameter_read_description_is_the_note(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    discovery = MagicMock()
    discovery.get_record_types = AsyncMock(return_value=[])
    monkeypatch.setattr(param_resolution, "get_discovery_service", lambda: discovery)

    async def _details(
        ctx: SearchContext, **_: object
    ) -> tuple[WDKSearchResponse, str]:
        return _single_copy_response(), ctx.record_type

    monkeypatch.setattr(param_resolution, "fetch_search_details", _details)

    result = await get_search_parameters(
        SearchContext("orthomcl", "group", "GroupsBySingleCopy")
    )

    assert result.description is not None
    assert _holds_the_note(result.description)

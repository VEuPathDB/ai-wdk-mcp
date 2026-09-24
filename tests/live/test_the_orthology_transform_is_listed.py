"""Each site's transform listing holds the orthology transform, against the real service."""

from __future__ import annotations

from typing import cast

import pytest
from veupathdb.wdk import WDKSearch, get_wdk_client

from veupathdb_mcp.catalog import searches
from veupathdb_mcp.catalog.discovery_service import DiscoveryService

pytestmark = pytest.mark.live_wdk

SITES = ("fungidb", "plasmodb", "toxodb", "vectorbase", "veupathdb")


class _SiteListing:
    """The searches a site lists for a record type now, read from WDK."""

    async def get_searches(self, site_id: str, record_type: str) -> list[WDKSearch]:
        return await get_wdk_client(site_id).get_searches(record_type)


@pytest.mark.parametrize("site_id", SITES)
async def test_the_orthology_transform_is_listed(
    site_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    listing = cast("DiscoveryService", _SiteListing())
    monkeypatch.setattr(searches, "get_discovery_service", lambda: listing)

    rows = await searches.list_transforms(site_id, "transcript")

    names = [row["name"] for row in rows]
    assert "GenesByOrthologs" in names
    assert "TranscriptsFromGenes" in names
    assert not [name for name in names if name.startswith("boolean_question")]

"""A site whose catalog is recorded search bodies, for a separation's enumeration."""

from __future__ import annotations

from collections.abc import Sequence

import pytest
from veupathdb.wdk import WDKSearch, WDKSearchResponse

from veupathdb_mcp.catalog import ParameterInfo, format_param_info_typed
from veupathdb_mcp.catalog.models import SearchMatch
from veupathdb_mcp.separation import enumerate as enumeration
from veupathdb_mcp.wdk.enrichment import GeneIdEnrichment

FALCIPARUM = "Plasmodium falciparum 3D7"


class RecordedCatalog:
    """The catalog listing and the parameter reads, from recorded definitions."""

    def __init__(self, responses: Sequence[WDKSearchResponse]) -> None:
        self.by_name: dict[str, WDKSearch] = {
            r.search_data.url_segment: r.search_data for r in responses
        }
        self.reads: list[tuple[str, dict[str, str]]] = []

    async def get_searches(self, site_id: str, record_type: str) -> list[WDKSearch]:
        del site_id, record_type
        return list(self.by_name.values())

    def wdk_fetch_at(self, site_id: str, record_type: str, search_name: str):
        del site_id, record_type
        search = self.by_name[search_name]

        async def fetch(context: dict[str, str]) -> list[ParameterInfo]:
            self.reads.append((search_name, dict(context)))
            return format_param_info_typed(search.parameters or [])

        return fetch


def patch_site(
    monkeypatch: pytest.MonkeyPatch,
    responses: Sequence[WDKSearchResponse],
    *,
    hits: Sequence[str] = (),
    enrichment: GeneIdEnrichment | None = None,
) -> RecordedCatalog:
    """Answer the enumeration's catalog, ranking and enrichment reads."""
    catalog = RecordedCatalog(responses)
    monkeypatch.setattr(enumeration, "get_discovery_service", lambda: catalog)
    monkeypatch.setattr(enumeration, "wdk_fetch_at", catalog.wdk_fetch_at)

    async def ranked(
        site_id: str, record_type: str, query: str, **kwargs: object
    ) -> list[SearchMatch]:
        del site_id, kwargs
        return [
            SearchMatch(
                name=name, display_name=name, description=query, record_type=record_type
            )
            for name in hits
        ]

    async def enriched(*args: object) -> GeneIdEnrichment:
        assert enrichment is not None
        return enrichment

    monkeypatch.setattr(enumeration, "search_for_searches", ranked)
    monkeypatch.setattr(enumeration, "enrich_gene_ids_by_value", enriched)
    return catalog

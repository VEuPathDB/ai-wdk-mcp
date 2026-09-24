"""Which searches each catalog listing offers.

A search that takes an input step is offered whatever its question set. The
boolean question is offered by none of them.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest
from tests._support.recorded_searches import recorded_search
from veupathdb.wdk import WDKSearch

from veupathdb_mcp.catalog import searches
from veupathdb_mcp.catalog.discovery_service import DiscoveryService
from veupathdb_mcp.catalog.search_collection import collect_search_candidates

_LISTING = Path(__file__).parent / "fixtures" / "plasmodb_transcript_searches.json"


def _site_listing() -> list[WDKSearch]:
    body = json.loads(_LISTING.read_text())["body"]
    return [WDKSearch.model_validate(entry) for entry in body]


def _orthologs() -> WDKSearch:
    return recorded_search("search_genes_by_orthologs").search_data


def _boolean() -> WDKSearch:
    return recorded_search("search_boolean_transcript").search_data


class _Catalog:
    def get_search_category(self, search_name: str) -> str | None:
        del search_name
        return None


class _Discovery:
    def __init__(self, listing: list[WDKSearch]) -> None:
        self._listing = listing

    async def get_searches(self, site_id: str, record_type: str) -> list[WDKSearch]:
        del site_id, record_type
        return list(self._listing)

    async def get_catalog(self, site_id: str) -> _Catalog:
        del site_id
        return _Catalog()


def _discovery(listing: list[WDKSearch]) -> DiscoveryService:
    return cast("DiscoveryService", _Discovery(listing))


@pytest.fixture
def site(monkeypatch: pytest.MonkeyPatch) -> DiscoveryService:
    """The recorded plasmodb searches, with the orthology and boolean definitions."""
    discovery = _discovery([_orthologs(), _boolean(), *_site_listing()])
    monkeypatch.setattr(searches, "get_discovery_service", lambda: discovery)
    return discovery


class TestTheTransformListing:
    async def test_the_orthology_transform_under_internal_questions_is_listed(
        self, site: DiscoveryService
    ) -> None:
        del site
        assert _orthologs().full_name == "InternalQuestions.GenesByOrthologs"

        rows = await searches.list_transforms("plasmodb", "transcript")

        assert "GenesByOrthologs" in [row["name"] for row in rows]

    async def test_the_boolean_question_is_not_listed(
        self, site: DiscoveryService
    ) -> None:
        del site
        rows = await searches.list_transforms("plasmodb", "transcript")

        assert _boolean().url_segment not in [row["name"] for row in rows]

    async def test_every_search_that_takes_an_input_step_is_listed(
        self, site: DiscoveryService
    ) -> None:
        del site
        rows = await searches.list_transforms("plasmodb", "transcript")

        assert [row["name"] for row in rows] == [
            "GenesByOrthologs",
            "TranscriptsFromGenes",
            "GenesBySpanLogic",
        ]

    async def test_the_boolean_question_is_known_by_its_shape_not_its_name(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        renamed = _boolean().model_copy(
            update={"url_segment": "CombineAnyName", "full_name": "Q.CombineAnyName"}
        )
        discovery = _discovery([renamed])
        monkeypatch.setattr(searches, "get_discovery_service", lambda: discovery)

        rows = await searches.list_transforms("plasmodb", "transcript")

        assert rows == []


class TestTheOtherListings:
    async def test_the_search_listing_holds_the_transform_and_not_the_boolean(
        self, site: DiscoveryService
    ) -> None:
        del site
        rows = await searches.list_searches("plasmodb", "transcript")

        assert [row["name"] for row in rows] == [
            "GenesByOrthologs",
            "TranscriptsFromGenes",
            "GenesBySpanLogic",
        ]

    async def test_the_categories_name_the_transform_and_not_the_boolean(
        self, site: DiscoveryService
    ) -> None:
        del site
        groups = await searches.browse_search_categories("plasmodb", "transcript")

        assert [group["examples"] for group in groups] == [
            [
                "Transform by Orthology",
                "Transform Transcripts to Genes",
                "Genes by Relative Location",
            ]
        ]

    async def test_the_ranking_candidates_hold_the_transform_and_not_the_boolean(
        self, site: DiscoveryService
    ) -> None:
        candidates = await collect_search_candidates(site, "plasmodb", ["transcript"])

        assert [search.url_segment for search, _ in candidates] == [
            "GenesByOrthologs",
            "TranscriptsFromGenes",
            "GenesBySpanLogic",
        ]

"""A search of any record type checks its organisms against the organism search,
read under the record type the catalog lists that search under."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from veupathdb.domain import SearchContext
from veupathdb.errors import VEuPathDBError, VEuPathDBErrorCode
from veupathdb.wdk import WDKSearchResponse

from veupathdb_mcp import catalog
from veupathdb_mcp.catalog import searches

SITE = "vectorbase"


def _definition(
    search_name: str, param: str, organisms: list[str]
) -> WDKSearchResponse:
    return WDKSearchResponse.model_validate(
        {
            "searchData": {
                "urlSegment": search_name,
                "fullName": f"Questions.{search_name}",
                "displayName": search_name,
                "parameters": [
                    {
                        "name": param,
                        "type": "multi-pick-vocabulary",
                        "displayName": "Organism",
                        "displayType": "treeBox",
                        "properties": {"organismProperties": ["organism"]},
                        "vocabulary": {
                            "data": {"term": "@@fake@@", "display": "@@fake@@"},
                            "children": [
                                {
                                    "data": {"term": name, "display": name},
                                    "children": [],
                                }
                                for name in organisms
                            ],
                        },
                    }
                ],
            },
            "validation": {"level": "DISPLAYABLE", "isValid": True},
        }
    )


def _site(
    monkeypatch: pytest.MonkeyPatch, dataset_organisms: list[str]
) -> list[SearchContext]:
    served = {
        ("transcript", "GenesByTaxon"): _definition(
            "GenesByTaxon",
            "organism",
            ["Anopheles gambiae PEST", "Anopheles coluzzii AcolN3"],
        ),
        ("dataset", "DatasetsByText"): _definition(
            "DatasetsByText", "text_search_organism", dataset_organisms
        ),
    }
    read: list[SearchContext] = []

    async def _details(ctx: SearchContext) -> WDKSearchResponse:
        read.append(ctx)
        found = served.get((ctx.record_type, ctx.search_name))
        if found is None:
            raise VEuPathDBError(VEuPathDBErrorCode.WDK_ERROR, "no such search")
        return found

    listing = MagicMock()
    listing.find_record_type_for_search = MagicMock(
        side_effect=lambda name: "transcript" if name == "GenesByTaxon" else None
    )
    discovery = MagicMock()
    discovery.get_search_details = AsyncMock(side_effect=_details)
    discovery.get_catalog = AsyncMock(return_value=listing)
    monkeypatch.setattr(searches, "get_discovery_service", lambda: discovery)
    return read


async def test_a_dataset_search_reads_the_organism_list_under_its_own_record_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    read = _site(monkeypatch, ["Anopheles", "Anopheles gambiae PEST"])

    name = await catalog.organism_parameter(SITE, "dataset", "DatasetsByText")

    assert name == "text_search_organism"
    assert [(ctx.record_type, ctx.search_name) for ctx in read] == [
        ("dataset", "DatasetsByText"),
        ("transcript", "GenesByTaxon"),
    ]


async def test_a_dataset_search_naming_no_listed_organism_has_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _site(monkeypatch, ["sample A", "sample B"])

    name = await catalog.organism_parameter(SITE, "dataset", "DatasetsByText")

    assert name is None

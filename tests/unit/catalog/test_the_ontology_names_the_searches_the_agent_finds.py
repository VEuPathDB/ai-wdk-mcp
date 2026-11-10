from __future__ import annotations

from pathlib import Path

from veupathdb.wdk import WDKSearch

from veupathdb_mcp.catalog.catalog_metadata import load_ontology_categories
from veupathdb_mcp.catalog.discovery import CatalogPolicy, SearchCatalog
from veupathdb_mcp.catalog.disk_cache import CatalogSnapshot


def _leaf(
    name: str, *, target: str = "search", scope: list[str] | None = None
) -> dict[str, object]:
    properties: dict[str, list[str]] = {
        "name": [name],
        "targetType": [target],
        "recordClassName": ["TranscriptRecordClasses.TranscriptRecordClass"],
    }
    if scope is not None:
        properties["scope"] = scope
    return {"children": [], "properties": properties}


_ONTOLOGY = {
    "name": "Categories",
    "tree": {
        "children": [
            _leaf("InternalQuestions.GenesByCompoundsTransform"),
            _leaf("SpanQuestions.DynSpansByEQTLtoGenes", scope=["webservice", "menu"]),
            {
                "children": [
                    _leaf("DatasetQuestions.MapStudiesForToolbar", scope=["internal"]),
                    _leaf("OrganismQuestions.GenomeDataTypes", scope=["menu"]),
                    _leaf("GeneAttributes.product", target="attribute"),
                ],
                "properties": {"label": ["searchCategory-nested"]},
            },
        ],
        "properties": {},
    },
}


class _Site:
    async def get(self, path: str) -> object:
        assert path == "/ontologies/Categories"
        return _ONTOLOGY


async def test_a_search_is_offered_when_its_scope_is_absent_or_names_the_webservice_or_menu() -> (
    None
):
    ontology = await load_ontology_categories(_Site(), "plasmodb")

    assert ontology.offered_searches == frozenset(
        {
            "InternalQuestions.GenesByCompoundsTransform",
            "SpanQuestions.DynSpansByEQTLtoGenes",
            "OrganismQuestions.GenomeDataTypes",
        }
    )


def _search(full_name: str) -> WDKSearch:
    return WDKSearch(
        url_segment=full_name.rsplit(".", maxsplit=1)[-1],
        full_name=full_name,
        display_name=full_name,
    )


def _catalog(tmp_path: Path, offered: list[str]) -> SearchCatalog:
    catalog = SearchCatalog(
        "plasmodb",
        cache_dir=tmp_path,
        policy=CatalogPolicy(refresh=False, sync=False),
        spawn=lambda coro, *, name=None: coro.close(),
    )
    catalog._restore_from_snapshot(
        CatalogSnapshot(
            record_types=[],
            searches={},
            datasets=[],
            search_categories={},
            available_categories=[],
            offered_searches=offered,
        )
    )
    return catalog


def test_the_catalog_lists_only_a_search_its_ontology_offers(tmp_path: Path) -> None:
    catalog = _catalog(tmp_path, ["GeneQuestions.GenesByOrthologPattern"])

    assert [
        catalog.lists(_search(name))
        for name in (
            "GeneQuestions.GenesByOrthologPattern",
            "GeneQuestions.GenesByEdaSubset",
        )
    ] == [True, False]


def test_a_catalog_whose_ontology_did_not_load_lists_every_search(
    tmp_path: Path,
) -> None:
    catalog = _catalog(tmp_path, [])

    assert [catalog.lists(_search("GeneQuestions.GenesByEdaSubset"))] == [True]


def test_a_search_the_ontology_offers_is_still_ranked_by_the_site_marks(
    tmp_path: Path,
) -> None:
    catalog = _catalog(tmp_path, ["InternalQuestions.GenesByOrthologs"])

    assert [catalog.ranks(_search("InternalQuestions.GenesByOrthologs"))] == [False]

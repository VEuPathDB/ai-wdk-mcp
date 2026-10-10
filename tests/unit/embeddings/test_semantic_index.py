"""The text a search is indexed by, and the fields it draws on."""

from __future__ import annotations

from veupathdb.wdk import WDKAttributeField, WDKSearch

from veupathdb_mcp.embeddings.fake import FakeEmbedder
from veupathdb_mcp.embeddings.semantic_index import SemanticSearchIndex


def _text(search: WDKSearch) -> str:
    return SemanticSearchIndex()._build_enriched_text(search, {}, frozenset())


def test_a_dynamic_attribute_contributes_its_display_name() -> None:
    text = _text(
        WDKSearch(
            url_segment="GenesByMolecularWeight",
            display_name="Molecular weight",
            dynamic_attributes=[
                WDKAttributeField(
                    name="matched_result", display_name="Met Search Criteria"
                )
            ],
        )
    )
    assert "Met Search Criteria" in text


def test_the_search_weight_attribute_is_left_out() -> None:
    """Every search carries it, so it separates none of them."""
    text = _text(
        WDKSearch(
            url_segment="GenesByMolecularWeight",
            display_name="Molecular weight",
            dynamic_attributes=[
                WDKAttributeField(name="wdk_weight", display_name="Search Weight")
            ],
        )
    )
    assert "Search Weight" not in text


def test_a_dynamic_attribute_parses_from_the_recorded_wire_shape() -> None:
    """The wire element carries keys the model does not declare."""
    search = WDKSearch.model_validate(
        {
            "urlSegment": "GenesByMolecularWeight",
            "displayName": "Molecular weight",
            "dynamicAttributes": [
                {
                    "name": "matched_result",
                    "displayName": "Met Search Criteria",
                    "isInReport": True,
                    "truncateTo": 100,
                    "columnDataType": "STRING",
                    "tools": {"reports": [], "filters": []},
                    "formats": [],
                    "properties": {"organisms": ["P. falciparum"]},
                }
            ],
        }
    )
    assert search.dynamic_attributes[0].display_name == "Met Search Criteria"
    assert "Met Search Criteria" in _text(search)


async def test_an_unknown_search_has_no_similarity(
    fake_embedder: FakeEmbedder,
) -> None:
    """A name the catalog does not hold is answered without an embedding call."""
    index = SemanticSearchIndex(site_id="plasmodb")
    index.collect(
        {"transcript": [WDKSearch(url_segment="GenesByText", display_name="Text")]}
    )

    assert await index.similarity("predicted GPI anchor", "GenesByNothing") is None
    assert fake_embedder.calls == []


def _collected(*searches: WDKSearch) -> dict[str, str]:
    index = SemanticSearchIndex(site_id="fungidb")
    index.collect({"transcript": list(searches)})
    return {entry.search_name: entry.enriched_text for entry in index.entries}


def test_a_property_every_search_shares_is_left_out() -> None:
    texts = _collected(
        WDKSearch(
            url_segment="GenesByAlpha",
            display_name="Alpha expression",
            properties={"organisms": ["Organism Shared"], "kind": ["alpha"]},
        ),
        WDKSearch(
            url_segment="GenesByBeta",
            display_name="Beta expression",
            properties={"organisms": ["Organism Shared"], "kind": ["beta"]},
        ),
    )
    assert "Organism Shared" not in texts["GenesByAlpha"]
    assert "Organism Shared" not in texts["GenesByBeta"]


def test_a_property_that_varies_between_searches_is_kept() -> None:
    texts = _collected(
        WDKSearch(
            url_segment="GenesByAlpha",
            display_name="Alpha expression",
            properties={"organisms": ["Organism Shared"], "kind": ["alpha"]},
        ),
        WDKSearch(
            url_segment="GenesByBeta",
            display_name="Beta expression",
            properties={"organisms": ["Organism Shared"], "kind": ["beta"]},
        ),
    )
    assert texts["GenesByAlpha"].startswith("alpha Alpha expression")
    assert texts["GenesByBeta"].startswith("beta Beta expression")


def test_a_property_only_some_searches_carry_is_kept() -> None:
    texts = _collected(
        WDKSearch(
            url_segment="GenesByAlpha",
            display_name="Alpha expression",
            properties={"kind": ["alpha"]},
        ),
        WDKSearch(url_segment="GenesByBeta", display_name="Beta expression"),
    )
    assert texts["GenesByAlpha"].startswith("alpha Alpha expression")


def test_a_shared_property_is_judged_across_record_types() -> None:
    index = SemanticSearchIndex(site_id="fungidb")
    index.collect(
        {
            "transcript": [
                WDKSearch(
                    url_segment="GenesByAlpha",
                    display_name="Alpha expression",
                    properties={"kind": ["shared"]},
                )
            ],
            "popsetSequence": [
                WDKSearch(
                    url_segment="PopsetByBeta",
                    display_name="Beta isolates",
                    properties={"kind": ["beta"]},
                )
            ],
        }
    )
    texts = {entry.search_name: entry.enriched_text for entry in index.entries}
    assert texts["GenesByAlpha"].startswith("shared Alpha expression")

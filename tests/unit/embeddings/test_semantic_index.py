"""The text a search is indexed by, and the fields it draws on."""

from __future__ import annotations

from veupathdb.wdk import WDKAttributeField, WDKSearch

from veupathdb_mcp.embeddings.semantic_index import SemanticSearchIndex


def _text(search: WDKSearch) -> str:
    return SemanticSearchIndex()._build_enriched_text(search, {})


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

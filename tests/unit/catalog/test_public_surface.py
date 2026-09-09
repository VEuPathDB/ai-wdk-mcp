"""A host reads the catalog through the package surface, never a private module."""

from __future__ import annotations

from veupathdb_mcp import catalog
from veupathdb_mcp.catalog import _param_filters
from veupathdb_mcp.catalog.param_formatting import ParameterInfo


def _filter_param(name: str) -> ParameterInfo:
    return ParameterInfo(
        name=name,
        display_name=name,
        type="filter",
        required=True,
        is_visible=True,
        help="",
        value_format="",
    )


def test_has_contrast_sibling_is_the_private_function() -> None:
    assert catalog.has_contrast_sibling is _param_filters.has_contrast_sibling
    assert "has_contrast_sibling" in catalog.__all__


def test_the_public_name_reports_a_contrast_pair() -> None:
    reference = _filter_param("ref_sample")
    comparison = _filter_param("comp_sample")
    unpaired = _filter_param("ref_other")

    assert catalog.has_contrast_sibling(reference, [reference, comparison])
    assert catalog.has_contrast_sibling(comparison, [reference, comparison])
    assert not catalog.has_contrast_sibling(unpaired, [unpaired, comparison])


def test_the_parameter_view_is_read_from_the_package() -> None:
    """A host that snapshots a parameter reads this package's own type."""
    assert catalog.ParameterInfo is ParameterInfo
    assert "ParameterInfo" in catalog.__all__


class TestTheUniversalSearches:
    def test_they_are_read_from_the_package(self) -> None:
        assert "UNIVERSAL_SEARCHES" in catalog.__all__

    def test_the_gene_text_search_is_one_of_them(self) -> None:
        names = [search.name for search in catalog.UNIVERSAL_SEARCHES]

        assert names == ["GenesByText"]

    def test_it_carries_the_shape_a_ranked_match_carries(self) -> None:
        entry = catalog.UNIVERSAL_SEARCHES[0].to_dict()

        assert entry == {
            "name": "GenesByText",
            "displayName": "Gene Text Search",
            "description": (
                "Search all text fields for genes matching a keyword or phrase."
            ),
            "recordType": "transcript",
            "category": "general",
            "returns": "transcript",
        }

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

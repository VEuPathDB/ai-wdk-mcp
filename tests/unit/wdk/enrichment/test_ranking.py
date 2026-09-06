"""Wire labels for enrichment values that can be None.

An unbounded ratio gets an ASCII label. A probability that is not computable
has no number to write.
"""

from __future__ import annotations

from veupathdb_mcp.wdk.enrichment.ranking import (
    UNBOUNDED_RATIO_LABEL,
    probability_cell,
    ratio_cell,
)


def test_an_unbounded_ratio_renders_as_an_ascii_label() -> None:
    assert UNBOUNDED_RATIO_LABEL == "Inf"
    assert ratio_cell(None) == "Inf"
    assert ratio_cell(3.4812345) == 3.4812


def test_a_probability_that_is_not_computable_renders_as_an_empty_cell() -> None:
    assert probability_cell(None) == ""
    assert probability_cell(3.4e-13) == 3.4e-13

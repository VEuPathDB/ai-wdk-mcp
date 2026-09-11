"""A non-finite WDK enrichment value becomes None, never a finite number.

WDK sends "Infinity" for a ratio whose denominator is zero. A finite stand-in
would rank the strongest term last and read a missing probability as certain.
"""

from __future__ import annotations

import pytest
from veupathdb import JSONObject

from veupathdb_mcp.wdk.enrichment.types import EnrichmentTerm


def _row(**overrides: object) -> JSONObject:
    row: JSONObject = {
        "term_id": "GO:0004672",
        "term_name": "protein kinase activity",
        "gene_count": 3,
        "background_count": 120,
        "fold_enrichment": "3.48",
        "odds_ratio": "4.12",
        "p_value": "0.0001",
        "fdr": "0.002",
        "bonferroni": "0.005",
    }
    row.update(overrides)
    return row


def test_finite_wdk_strings_still_coerce_to_floats() -> None:
    term = EnrichmentTerm.model_validate(_row())

    assert term.fold_enrichment == pytest.approx(3.48)
    assert term.odds_ratio == pytest.approx(4.12)
    assert term.p_value == pytest.approx(0.0001)
    assert term.fdr == pytest.approx(0.002)
    assert term.bonferroni == pytest.approx(0.005)


def test_a_ratio_keeps_four_decimal_places_on_the_wire() -> None:
    term = EnrichmentTerm.model_validate(_row(fold_enrichment="3.4812345"))

    assert term.model_dump(by_alias=True)["foldEnrichment"] == 3.4812


@pytest.mark.parametrize("raw", ["Infinity", "-Infinity", float("inf"), float("-inf")])
def test_an_unbounded_odds_ratio_is_none(raw: object) -> None:
    term = EnrichmentTerm.model_validate(_row(odds_ratio=raw))

    assert term.odds_ratio is None
    assert term.fold_enrichment == pytest.approx(3.48)


@pytest.mark.parametrize("raw", ["Infinity", float("inf")])
def test_an_unbounded_fold_enrichment_is_none(raw: object) -> None:
    term = EnrichmentTerm.model_validate(_row(fold_enrichment=raw))

    assert term.fold_enrichment is None
    assert term.model_dump(by_alias=True)["foldEnrichment"] is None


@pytest.mark.parametrize("field", ["p_value", "fdr", "bonferroni"])
@pytest.mark.parametrize("raw", ["NaN", float("nan"), "Infinity"])
def test_a_probability_that_is_not_computable_is_none(field: str, raw: object) -> None:
    term = EnrichmentTerm.model_validate(_row(**{field: raw}))

    assert getattr(term, field) is None


def test_a_non_numeric_string_still_fails_validation() -> None:
    with pytest.raises(ValueError, match="p_value"):
        EnrichmentTerm.model_validate(_row(p_value="not a number"))

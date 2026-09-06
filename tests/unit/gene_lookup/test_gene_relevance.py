from __future__ import annotations

import pytest

from veupathdb_mcp.gene_lookup.result import GeneResult
from veupathdb_mcp.gene_lookup.scoring import score_gene_relevance


def test_exact_product_match_adds_descriptive_bonus() -> None:
    result = GeneResult(gene_id="", product="alpha tubulin")
    assert score_gene_relevance("alpha tubulin", result) == pytest.approx(115.0)


def test_exact_gene_id_with_primary_field_no_descriptive_bonus() -> None:
    result = GeneResult(gene_id="PF3D7_0708400", matched_fields=["gene_source_id"])
    assert score_gene_relevance("PF3D7_0708400", result) == pytest.approx(120.0)


def test_secondary_matched_field_applies_penalty() -> None:
    result = GeneResult(gene_id="abc", matched_fields=["gene_Notes"])
    assert score_gene_relevance("abc", result) == pytest.approx(90.0)


def test_prefix_descriptive_match_at_threshold_gets_bonus() -> None:
    result = GeneResult(gene_id="", product="alpha tubulin chain")
    assert score_gene_relevance("alpha tubulin", result) == pytest.approx(109.25)


def test_substring_descriptive_match_below_threshold_gets_no_bonus() -> None:
    result = GeneResult(gene_id="", product="contains alpha tubulin here")
    assert score_gene_relevance("alpha tubulin", result) == pytest.approx(28.0)

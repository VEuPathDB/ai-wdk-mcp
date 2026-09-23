"""The serialized shape of one ranked search."""

from __future__ import annotations

from veupathdb_mcp.catalog.models import SearchMatch


def _match(semantic_similarity: float | None) -> SearchMatch:
    return SearchMatch(
        name="GenesByExportPrediction",
        display_name="Exported Protein",
        description="",
        record_type="transcript",
        relevance=1.0,
        semantic_similarity=semantic_similarity,
    )


def test_the_raw_cosine_is_serialized_beside_the_relevance() -> None:
    entry = _match(0.214).to_dict()

    assert entry["relevance"] == 1.0
    assert entry["semanticSimilarity"] == 0.21


def test_an_unscored_search_carries_no_cosine() -> None:
    assert "semanticSimilarity" not in _match(None).to_dict()


def test_a_zero_cosine_is_still_a_cosine() -> None:
    assert _match(0.0).to_dict()["semanticSimilarity"] == 0.0

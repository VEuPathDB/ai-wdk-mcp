"""The search-catalog half: the query guard, and the surface it keeps clean.

Every function here takes a site and its arguments by value, so one served call
carries no agent state.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any
from unittest.mock import MagicMock

import pytest
from veupathdb.wdk import WDKSearch

from veupathdb_mcp.catalog import searches
from veupathdb_mcp.catalog.models import SearchMatch
from veupathdb_mcp.catalog.search_inspection import (
    inspect_search,
    read_parameter_options,
)
from veupathdb_mcp.catalog.searches import VagueSearchQueryError


class TestSearchQueryGuard:
    async def test_an_empty_query_is_refused(self) -> None:
        with pytest.raises(VagueSearchQueryError) as excinfo:
            await searches.search_for_searches("plasmodb", "transcript", "")

        assert excinfo.value.rejection.error == "query_required"

    async def test_a_one_word_query_is_refused(self) -> None:
        with pytest.raises(VagueSearchQueryError) as excinfo:
            await searches.search_for_searches("plasmodb", "transcript", "gene")

        rejection = excinfo.value.rejection
        assert rejection.error == "query_too_vague"
        assert rejection.query == "gene"
        assert rejection.examples

    async def test_keywords_carry_a_short_query(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        recorded: dict[str, Any] = {}

        async def _resolve(*_a: Any, **_k: Any) -> list[str]:
            recorded["called"] = True
            return ["transcript"]

        monkeypatch.setattr(searches, "resolve_record_types", _resolve)
        monkeypatch.setattr(searches, "get_discovery_service", MagicMock())

        async def _collect(*_a: Any, **_k: Any) -> list[Any]:
            return []

        async def _no_bonus(*_a: Any, **_k: Any) -> None:
            return None

        monkeypatch.setattr(searches, "collect_search_candidates", _collect)
        monkeypatch.setattr(searches, "apply_site_search_bonus", _no_bonus)
        monkeypatch.setattr(searches, "apply_semantic_bonus", _no_bonus)

        result = await searches.search_for_searches(
            "plasmodb", "transcript", "gene", keywords=["Su_strand_specific"]
        )

        assert result == []
        assert recorded["called"] is True


_CANDIDATES = [
    (
        WDKSearch(
            url_segment="GenesByExportPrediction",
            display_name="Exported Protein",
            description="PEXEL export motif prediction",
        ),
        "transcript",
    ),
    (
        WDKSearch(
            url_segment="GenesByMolecularWeight",
            display_name="Molecular Weight",
            description="predicted molecular weight of the protein",
        ),
        "transcript",
    ),
]


def _rank_over(
    monkeypatch: pytest.MonkeyPatch,
    cosines: dict[str, float] | None = None,
) -> None:
    """Rank the fixed candidates, with the index answering the given cosines."""

    async def _resolve(*_a: Any, **_k: Any) -> list[str]:
        return ["transcript"]

    async def _collect(*_a: Any, **_k: Any) -> list[tuple[WDKSearch, str]]:
        return list(_CANDIDATES)

    async def _no_site_bonus(*_a: Any, **_k: Any) -> None:
        return None

    async def _semantic(
        scored: list[tuple[float, SearchMatch]], *_a: Any, **_k: Any
    ) -> None:
        for i, (sc, entry) in enumerate(scored):
            if entry.name in (cosines or {}):
                sim = (cosines or {})[entry.name]
                scored[i] = (sc + 70.0 * sim, replace(entry, semantic_similarity=sim))

    monkeypatch.setattr(searches, "resolve_record_types", _resolve)
    monkeypatch.setattr(searches, "get_discovery_service", MagicMock())
    monkeypatch.setattr(searches, "collect_search_candidates", _collect)
    monkeypatch.setattr(searches, "apply_site_search_bonus", _no_site_bonus)
    monkeypatch.setattr(searches, "apply_semantic_bonus", _semantic)


class TestWhatTheRankingReturns:
    async def test_a_query_that_matches_nothing_returns_no_search(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _rank_over(monkeypatch)

        result = await searches.search_for_searches(
            "plasmodb", "transcript", "glycosylphosphatidylinositol anchored"
        )

        assert result == []

    async def test_a_search_nothing_matched_is_not_a_result(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _rank_over(monkeypatch)

        result = await searches.search_for_searches(
            "plasmodb", "transcript", "molecular weight"
        )

        assert [match.name for match in result] == ["GenesByMolecularWeight"]

    async def test_relevance_is_relative_to_the_best_hit(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The best of weak hits reads 1.0, so relevance alone says no match."""
        _rank_over(
            monkeypatch,
            {"GenesByExportPrediction": 0.2, "GenesByMolecularWeight": 0.1},
        )

        result = await searches.search_for_searches(
            "plasmodb", "transcript", "glycosylphosphatidylinositol anchored"
        )

        assert [match.name for match in result] == [
            "GenesByExportPrediction",
            "GenesByMolecularWeight",
        ]
        assert result[0].relevance == pytest.approx(1.0)
        assert result[1].relevance == pytest.approx(0.5)

    async def test_the_raw_cosine_rides_on_each_match(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _rank_over(monkeypatch, {"GenesByExportPrediction": 0.2})

        result = await searches.search_for_searches(
            "plasmodb", "transcript", "exported protein weight"
        )

        by_name = {match.name: match for match in result}
        assert by_name["GenesByExportPrediction"].semantic_similarity == (
            pytest.approx(0.2)
        )
        assert by_name["GenesByMolecularWeight"].semantic_similarity is None


class TestTheServiceHalfCarriesNoAgentSurface:
    def test_the_split_halves_take_a_site_and_no_state(self) -> None:
        signatures = {
            "inspect_search": inspect_search,
            "read_parameter_options": read_parameter_options,
            "search_for_searches": searches.search_for_searches,
            "list_searches": searches.list_searches,
        }

        for name, function in signatures.items():
            params = list(
                function.__code__.co_varnames[: function.__code__.co_argcount]
            )
            assert params[0] == "site_id", name
            assert "ctx" not in params, name
            assert "agent_state" not in params, name
            assert "deps" not in params, name

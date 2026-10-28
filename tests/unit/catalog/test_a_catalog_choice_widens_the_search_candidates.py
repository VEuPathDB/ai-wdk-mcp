"""A Decisions choice over every offered search adds its picks after the ranking."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest
import respx
from scripts.record_decisions import CATALOG_QUERY, OFFERED
from veupathdb.wdk import WDKSearch

from veupathdb_mcp.catalog import post_decision, searches, use_decisions_transport
from veupathdb_mcp.catalog.decisions import DECISIONS_URL, MAX_CHOICES
from veupathdb_mcp.catalog.models import SearchMatch
from veupathdb_mcp.catalog.search_picks import catalog_choice_request

FIXTURE = Path(__file__).parent / "fixtures" / "decisions_plasmodb_catalog_choice.json"


def _recorded() -> dict[str, Any]:
    exchange: dict[str, Any] = json.loads(FIXTURE.read_text())["exchanges"][0]
    return exchange


def _rank_text_first(monkeypatch: pytest.MonkeyPatch) -> None:
    """The lexical and semantic ranking finds GenesByText and GenesByGoTerm only."""

    async def _resolve(*_a: Any, **_k: Any) -> list[str]:
        return ["transcript"]

    async def _collect(*_a: Any, **_k: Any) -> list[tuple[WDKSearch, str]]:
        return [(s, "transcript") for s in OFFERED]

    async def _no_site_bonus(*_a: Any, **_k: Any) -> None:
        return None

    async def _semantic(
        scored: list[tuple[float, SearchMatch]], *_a: Any, **_k: Any
    ) -> None:
        bonus = {"GenesByText": 60.0, "GenesByGoTerm": 40.0}
        scored[:] = [(bonus.get(e.name, 0.0), e) for _, e in scored]

    monkeypatch.setattr(searches, "resolve_record_types", _resolve)
    monkeypatch.setattr(searches, "get_discovery_service", MagicMock())
    monkeypatch.setattr(searches, "collect_search_candidates", _collect)
    monkeypatch.setattr(searches, "apply_site_search_bonus", _no_site_bonus)
    monkeypatch.setattr(searches, "apply_semantic_bonus", _semantic)


def _reach_the_service(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-a-key")
    use_decisions_transport(post_decision)


async def _rank() -> list[str]:
    result = await searches.search_for_searches("plasmodb", "transcript", CATALOG_QUERY)
    return [m.name for m in result]


class TestTheRequest:
    def test_the_offered_searches_are_one_question_of_named_choices(self) -> None:
        request = catalog_choice_request(
            "plasmodb", ["transcript"], CATALOG_QUERY, OFFERED
        )

        assert request is not None
        assert request.model_dump(mode="json") == _recorded()["request"]

    def test_a_large_catalog_is_split_into_even_chunks(self) -> None:
        many = [
            WDKSearch(url_segment=f"GenesBy{i}", display_name=f"S{i}")
            for i in range(600)
        ]

        request = catalog_choice_request("plasmodb", ["transcript"], "kinases", many)

        assert request is not None
        sizes = [len(q.model_dump()["choices"]) for q in request.questions]
        assert sizes == [200, 200, 200]
        assert max(sizes) <= MAX_CHOICES


class TestWhatTheRankingReturns:
    async def test_unanswered_the_ranking_stands(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _rank_text_first(monkeypatch)

        assert await _rank() == ["GenesByText", "GenesByGoTerm"]

    async def test_the_pick_the_ranking_missed_follows_it(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _rank_text_first(monkeypatch)
        _reach_the_service(monkeypatch)
        with respx.mock() as router:
            router.post(DECISIONS_URL).respond(json=_recorded()["response"])
            result = await searches.search_for_searches(
                "plasmodb", "transcript", CATALOG_QUERY
            )

        assert [m.name for m in result] == [
            "GenesByText",
            "GenesByGoTerm",
            "GenesByInterproDomain",
        ]
        by_name = {m.name: m.to_dict() for m in result}
        assert by_name["GenesByInterproDomain"]["decisionProbability"] == 1.0
        assert "relevance" not in by_name["GenesByInterproDomain"]
        assert by_name["GenesByText"]["relevance"] == 1.0
        assert "decisionProbability" not in by_name["GenesByText"]

    async def test_a_service_failure_leaves_the_ranking_as_it_stands(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _rank_text_first(monkeypatch)
        _reach_the_service(monkeypatch)
        with respx.mock() as router:
            router.post(DECISIONS_URL).mock(side_effect=httpx.ReadTimeout("slow"))
            names = await _rank()

        assert names == ["GenesByText", "GenesByGoTerm"]

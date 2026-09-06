"""The search-catalog half: the query guard, and the surface it keeps clean.

Every function here takes a site and its arguments by value, so one served call
carries no agent state.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from veupathdb_mcp.catalog import searches
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

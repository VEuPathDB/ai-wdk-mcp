"""A narrowed vocabulary read carries the entry a Decisions choice picks, and how sure it is."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import respx
from scripts.record_decisions import VOCAB_TERM
from veupathdb.domain.parameters import VocabOption
from veupathdb.wdk import WDKSearchResponse

from veupathdb_mcp.catalog import (
    post_decision,
    search_inspection,
    searches,
    use_decisions_transport,
)
from veupathdb_mcp.catalog.decisions import DECISIONS_URL
from veupathdb_mcp.catalog.param_formatting import ParameterInfo
from veupathdb_mcp.catalog.search_inspection import (
    VocabNarrowing,
    read_parameter_options,
)
from veupathdb_mcp.catalog.vocab_pick import VocabPick, pick_vocab_entry

FIXTURES = Path(__file__).parent / "fixtures"
INTERPRO = FIXTURES / "plasmodb_3d7_interpro_vocabulary_half_off.json"
PICK = FIXTURES / "decisions_plasmodb_interpro_pick.json"
CONTEXT = {"organism": ["Plasmodium falciparum 3D7"], "domain_database": "INTERPRO"}


def _exchanges() -> list[dict[str, Any]]:
    exchanges: list[dict[str, Any]] = json.loads(PICK.read_text())["exchanges"]
    return exchanges


def _serve_the_site(monkeypatch: pytest.MonkeyPatch) -> None:
    recorded = WDKSearchResponse.model_validate(
        json.loads(INTERPRO.read_text())["response_json"]
    )
    client = MagicMock()
    client.get_search_details = AsyncMock(return_value=recorded)
    client.get_search_details_with_params = AsyncMock(return_value=recorded)
    monkeypatch.setattr(searches, "get_wdk_client", lambda _site: client)
    monkeypatch.setattr(search_inspection, "get_wdk_client", lambda _site: client)


def _reach_the_service(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-a-key")
    use_decisions_transport(post_decision)


async def _read(narrowing: VocabNarrowing) -> ParameterInfo:
    read = await read_parameter_options(
        "plasmodb",
        "GenesByInterproDomain",
        "domain_typeahead",
        record_type="transcript",
        context_values=CONTEXT,
        narrowing=narrowing,
    )
    assert isinstance(read, ParameterInfo)
    return read


class TestTheRecordedInterProLookup:
    async def test_the_requests_sent_are_the_recorded_ones(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _serve_the_site(monkeypatch)
        _reach_the_service(monkeypatch)
        choice, fit = _exchanges()
        with respx.mock() as router:
            route = router.post(DECISIONS_URL).mock(
                side_effect=[
                    httpx.Response(200, json=choice["response"]),
                    httpx.Response(200, json=fit["response"]),
                ]
            )
            await _read(VocabNarrowing(query=VOCAB_TERM))

        sent = [json.loads(call.request.content) for call in route.calls]
        assert sent == [choice["request"], fit["request"]]

    async def test_a_confident_choice_the_fit_doubts_is_not_settled(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _serve_the_site(monkeypatch)
        _reach_the_service(monkeypatch)
        choice, fit = _exchanges()
        with respx.mock() as router:
            router.post(DECISIONS_URL).mock(
                side_effect=[
                    httpx.Response(200, json=choice["response"]),
                    httpx.Response(200, json=fit["response"]),
                ]
            )
            read = await _read(VocabNarrowing(query=VOCAB_TERM))

        assert read.vocab_pick is not None
        dumped = read.vocab_pick.model_dump(by_alias=True)
        assert dumped == {
            "value": "IPR011009",
            "display": "IPR011009 : Protein kinase-like (PK-like)",
            "choiceConfidence": 0.89,
            "fitProbability": 0.31,
            "minConfidence": 0.5,
            "offered": 22,
            "confidence": 0.31,
            "settled": False,
        }

    async def test_unanswered_the_read_carries_no_pick(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _serve_the_site(monkeypatch)

        read = await _read(VocabNarrowing(query=VOCAB_TERM))

        assert read.vocab_pick is None

    async def test_a_read_no_query_narrowed_asks_nothing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _serve_the_site(monkeypatch)
        _reach_the_service(monkeypatch)
        with respx.mock(assert_all_called=False) as router:
            route = router.post(DECISIONS_URL)
            read = await _read(VocabNarrowing())

        assert read.vocab_pick is None
        assert not route.called

    async def test_a_failed_fit_gives_no_pick(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _serve_the_site(monkeypatch)
        _reach_the_service(monkeypatch)
        choice, _ = _exchanges()
        with respx.mock() as router:
            router.post(DECISIONS_URL).mock(
                side_effect=[
                    httpx.Response(200, json=choice["response"]),
                    httpx.Response(503),
                ]
            )
            read = await _read(VocabNarrowing(query=VOCAB_TERM))

        assert read.vocab_pick is None


_ENTRIES = [
    VocabOption(value="GO:0000001", display="mitochondrion inheritance"),
    VocabOption(
        value="GO:0000002", display="obsolete mitochondrial genome maintenance"
    ),
]


def _none_fits(confidence: float) -> dict[str, Any]:
    return {
        "answers": [
            {
                "type": "choice",
                "name": "value",
                "choice": "none_fits",
                "probabilities": [
                    {"value": "e0", "probability": 0.1},
                    {"value": "e1", "probability": 0.1},
                    {"value": "none_fits", "probability": 0.8},
                ],
                "confidence": confidence,
            }
        ],
        "usage": {"input_tokens": 120},
    }


class TestTheShapeOfAPick:
    async def test_none_fits_is_a_pick_with_no_value_and_no_fit_asked(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _reach_the_service(monkeypatch)
        with respx.mock() as router:
            route = router.post(DECISIONS_URL).respond(json=_none_fits(0.72))
            pick = await pick_vocab_entry(
                "plasmodb", "GO Term", "mitochondrial genome upkeep", _ENTRIES
            )

        assert route.call_count == 1
        assert pick == VocabPick(choice_confidence=0.72, min_confidence=0.5, offered=2)
        assert pick.settled is False

    def test_the_threshold_is_the_setting(self) -> None:
        pick = VocabPick(
            value="GO:0000001",
            choice_confidence=0.9,
            fit_probability=0.55,
            min_confidence=0.6,
            offered=2,
        )

        assert pick.confidence == 0.55
        assert pick.settled is False
        assert pick.model_copy(update={"min_confidence": 0.5}).settled is True

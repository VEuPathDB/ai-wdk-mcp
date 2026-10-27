"""The Decisions client: the wire shape it sends, and what it answers on a failure."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx
from pydantic import ValidationError
from structlog.testing import capture_logs

from veupathdb_mcp.catalog.decisions import (
    DECISIONS_URL,
    Choice,
    ChoiceAnswer,
    ChoiceQuestion,
    DecisionRequest,
    DecisionResponse,
    PredicateQuestion,
    decide,
)
from veupathdb_mcp.settings import McpSettings

FIXTURE = Path(__file__).parent / "fixtures" / "decisions_plasmodb_interpro_pick.json"


def _exchange(index: int) -> tuple[DecisionRequest, dict[str, object]]:
    recorded = json.loads(FIXTURE.read_text())["exchanges"][index]
    return DecisionRequest.model_validate(recorded["request"]), recorded["response"]


def _turn_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DECISIONS_ENABLED", "true")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-a-key")


def _request() -> DecisionRequest:
    return DecisionRequest(
        input="VEuPathDB site: plasmodb.",
        questions=[
            ChoiceQuestion(
                name="v",
                instructions="Which value?",
                choices=[
                    Choice(value="e0", description="IPR011009 : Kinase-like_dom_sf"),
                    Choice(value="none_fits", description="None of these."),
                ],
            ),
            PredicateQuestion(name="p", instructions="The value is current."),
        ],
    )


class TestTheWireShape:
    def test_a_request_dumps_the_documented_fields(self) -> None:
        assert _request().model_dump(mode="json") == {
            "model": "gpt-6-luna",
            "input": "VEuPathDB site: plasmodb.",
            "questions": [
                {
                    "type": "choice",
                    "name": "v",
                    "instructions": "Which value?",
                    "choices": [
                        {
                            "value": "e0",
                            "description": "IPR011009 : Kinase-like_dom_sf",
                        },
                        {"value": "none_fits", "description": "None of these."},
                    ],
                },
                {
                    "type": "predicate",
                    "name": "p",
                    "instructions": "The value is current.",
                },
            ],
        }

    def test_a_choice_question_takes_at_most_255_choices(self) -> None:
        many = [Choice(value=f"e{i}", description="x") for i in range(256)]

        with pytest.raises(ValidationError):
            ChoiceQuestion(name="v", instructions="Which?", choices=many)

    def test_a_recorded_answer_parses_by_its_type(self) -> None:
        _, body = _exchange(0)
        response = DecisionResponse.model_validate(body)

        answer = response.choice("value")
        assert isinstance(answer, ChoiceAnswer)
        assert answer.ranked()[0].value == answer.choice == "e0"
        assert response.predicate("value") is None
        assert response.usage.input_tokens > 0


class TestWhenTheServiceIsOff:
    async def test_it_sends_nothing_and_answers_none(self) -> None:
        with respx.mock(assert_all_called=False) as router:
            route = router.post(DECISIONS_URL)
            assert await decide(_request(), purpose="test") is None

        assert not route.called

    def test_it_cannot_be_on_without_a_key(self) -> None:
        with pytest.raises(ValidationError, match="OPENAI_API_KEY"):
            McpSettings(decisions_enabled=True, openai_api_key="")


class TestWhenTheServiceIsOn:
    async def test_it_posts_the_request_with_the_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _turn_on(monkeypatch)
        request, body = _exchange(0)
        with respx.mock() as router:
            route = router.post(DECISIONS_URL).respond(json=body)
            response = await decide(request, purpose="test")

        sent = route.calls.last.request
        assert sent.headers["authorization"] == "Bearer sk-test-not-a-key"
        assert json.loads(sent.content) == request.model_dump(mode="json")
        assert response == DecisionResponse.model_validate(body)

    @pytest.mark.parametrize(
        "reply",
        [
            httpx.Response(500, json={"error": {"message": "overloaded"}}),
            httpx.Response(200, json={"answers": "not a list"}),
            httpx.ConnectTimeout("timed out"),
        ],
    )
    async def test_a_failure_is_logged_and_answers_none(
        self, monkeypatch: pytest.MonkeyPatch, reply: httpx.Response | Exception
    ) -> None:
        _turn_on(monkeypatch)
        with respx.mock() as router, capture_logs() as logs:
            router.post(DECISIONS_URL).mock(
                side_effect=reply if isinstance(reply, Exception) else None,
                return_value=None if isinstance(reply, Exception) else reply,
            )
            assert await decide(_request(), purpose="test") is None

        (event,) = [e for e in logs if e["log_level"] == "warning"]
        assert event["purpose"] == "test"
        assert "sk-test-not-a-key" not in json.dumps(event, default=str)

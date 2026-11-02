from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from veupathdb_mcp.catalog import (
    DECISIONS_URL,
    DecisionRequest,
    DecisionResponse,
    DecisionUsage,
    decide,
    post_decision,
    use_decisions_transport,
)

FIXTURE = Path(__file__).parent / "fixtures" / "decisions_plasmodb_interpro_pick.json"


def _recorded() -> dict[str, dict[str, object]]:
    exchange: dict[str, dict[str, object]] = json.loads(FIXTURE.read_text())[
        "exchanges"
    ][0]
    return exchange


@pytest.fixture(autouse=True)
def _the_library_transport_after(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-a-key")
    yield
    use_decisions_transport(post_decision)


async def test_a_host_transport_sees_each_request_and_its_usage() -> None:
    recorded = _recorded()
    request = DecisionRequest.model_validate(recorded["request"])
    seen: list[tuple[str, DecisionUsage]] = []

    async def send(sent: DecisionRequest) -> DecisionResponse:
        response = DecisionResponse.model_validate(recorded["response"])
        seen.append((sent.questions[0].name, response.usage))
        return response

    use_decisions_transport(send)
    answered = await decide(request, purpose="search candidates")

    assert answered is not None
    assert answered.choice(request.questions[0].name) is not None
    assert seen == [
        (
            request.questions[0].name,
            DecisionUsage(input_tokens=711, cached_tokens=0, cache_write_tokens=0),
        )
    ]
    assert DECISIONS_URL == "https://api.openai.com/v1/decisions"


def test_the_usage_reads_cached_and_written_tokens() -> None:
    usage = DecisionUsage.model_validate(
        {
            "input_tokens": 900,
            "input_tokens_details": {"cached_tokens": 600, "cache_write_tokens": 100},
        }
    )

    assert (usage.input_tokens, usage.cached_tokens, usage.cache_write_tokens) == (
        900,
        600,
        100,
    )

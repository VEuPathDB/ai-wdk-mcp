"""The OpenAI Decisions API: typed questions over shared evidence, typed answers.

The service is optional. Off, unreachable or answering a body that does not
parse, ``decide`` answers None and the caller keeps its own result.
"""

from __future__ import annotations

from typing import Annotated, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Discriminator, Field, ValidationError
from veupathdb import get_logger

from veupathdb_mcp.settings import get_mcp_settings

logger = get_logger(__name__)

DECISIONS_URL = "https://api.openai.com/v1/decisions"
MAX_CHOICES = 255
MAX_QUESTIONS = 400


class _Wire(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")


class Choice(_Wire):
    value: str
    description: str


class ChoiceQuestion(_Wire):
    type: Literal["choice"] = "choice"
    name: str
    instructions: str
    choices: list[Choice] = Field(min_length=2, max_length=MAX_CHOICES)


class PredicateQuestion(_Wire):
    type: Literal["predicate"] = "predicate"
    name: str
    instructions: str


Question = Annotated[ChoiceQuestion | PredicateQuestion, Discriminator("type")]


class DecisionRequest(_Wire):
    model: Literal["gpt-6-luna"] = "gpt-6-luna"
    input: str
    questions: list[Question] = Field(min_length=1, max_length=MAX_QUESTIONS)


class ChoiceProbability(_Wire):
    value: str
    probability: float


class ChoiceAnswer(_Wire):
    type: Literal["choice"]
    name: str
    choice: str
    probabilities: list[ChoiceProbability]
    confidence: float

    def ranked(self) -> list[ChoiceProbability]:
        """The choices by probability, highest first."""
        return sorted(self.probabilities, key=lambda p: -p.probability)


class PredicateAnswer(_Wire):
    type: Literal["predicate"]
    name: str
    probability: float


class RefusalAnswer(_Wire):
    type: Literal["refusal"]
    name: str


Answer = Annotated[
    ChoiceAnswer | PredicateAnswer | RefusalAnswer, Discriminator("type")
]


class DecisionUsage(_Wire):
    input_tokens: int = 0


class DecisionResponse(_Wire):
    answers: list[Answer]
    usage: DecisionUsage = Field(default_factory=DecisionUsage)

    def choice(self, name: str) -> ChoiceAnswer | None:
        """The choice answer to the question of this name, or None on a refusal."""
        for answer in self.answers:
            match answer:
                case ChoiceAnswer() if answer.name == name:
                    return answer
                case _:
                    pass
        return None

    def predicate(self, name: str) -> PredicateAnswer | None:
        """The predicate answer to the question of this name, or None on a refusal."""
        for answer in self.answers:
            match answer:
                case PredicateAnswer() if answer.name == name:
                    return answer
                case _:
                    pass
        return None


async def decide(request: DecisionRequest, *, purpose: str) -> DecisionResponse | None:
    """Ask the service, or None when it is off or does not answer."""
    settings = get_mcp_settings()
    if not settings.decisions_enabled:
        return None
    try:
        async with httpx.AsyncClient(
            timeout=settings.decisions_timeout_seconds
        ) as client:
            response = await client.post(
                DECISIONS_URL,
                json=request.model_dump(mode="json"),
                headers={"Authorization": f"Bearer {settings.openai_api_key}"},
            )
        response.raise_for_status()
        return DecisionResponse.model_validate_json(response.content)
    except (httpx.HTTPError, ValidationError) as exc:
        logger.warning(
            "Decisions did not answer; the catalog read keeps its own result",
            purpose=purpose,
            error_type=type(exc).__name__,
            error=str(exc)[:300],
        )
        return None

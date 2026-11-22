"""One resolver names the vocabulary entry a phrase states, under each arm."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

import pytest
from veupathdb.domain.parameters import (
    VocabOption,
    flatten_vocab,
    rank_entries,
)
from veupathdb.wdk import WDKSearchResponse

from veupathdb_mcp.catalog import (
    ChoiceQuestion,
    DecisionRequest,
    DecisionResponse,
    ResolveContext,
    resolve_entry,
    resolve_request,
    use_decisions_transport,
)

FIXTURES = Path(__file__).parent / "fixtures"
INTERPRO = FIXTURES / "plasmodb_3d7_interpro_vocabulary_half_off.json"
TAXON = FIXTURES / "plasmodb_genes_by_taxon.json"
PICK = FIXTURES / "decisions_plasmodb_interpro_pick.json"
DOMAINS = "Specific Domain(s)"
ABOUT = ResolveContext(site_id="plasmodb", message="")

type Arm = Literal["refuse", "choice", "choice_fit"]


def _options(fixture: Path, name: str) -> list[VocabOption]:
    search = WDKSearchResponse.model_validate(
        json.loads(fixture.read_text())["response_json"]
    )
    parameter = next(p for p in search.search_data.parameters if p.name == name)
    return flatten_vocab(parameter.vocabulary)


def _recorded() -> list[DecisionResponse]:
    exchanges: list[dict[str, Any]] = json.loads(PICK.read_text())["exchanges"]
    return [DecisionResponse.model_validate(e["response"]) for e in exchanges]


class _Stub:
    def __init__(self, answers: list[DecisionResponse | None]) -> None:
        self.answers = answers
        self.sent: list[DecisionRequest] = []

    async def __call__(self, request: DecisionRequest) -> DecisionResponse | None:
        self.sent.append(request)
        return self.answers.pop(0)


def _answering(answers: list[DecisionResponse | None]) -> _Stub:
    stub = _Stub(answers)
    use_decisions_transport(stub)
    return stub


def _choosing(choice: str, confidence: float) -> DecisionResponse:
    return DecisionResponse.model_validate(
        {
            "answers": [
                {
                    "type": "choice",
                    "name": "value",
                    "choice": choice,
                    "probabilities": [{"value": choice, "probability": confidence}],
                    "confidence": confidence,
                }
            ]
        }
    )


@pytest.fixture(scope="module")
def domains() -> list[VocabOption]:
    return _options(INTERPRO, "domain_typeahead")


@pytest.fixture(scope="module")
def organisms() -> list[VocabOption]:
    return _options(TAXON, "organism")


class TestTheRefuseArm:
    @pytest.mark.parametrize(
        ("phrase", "first"),
        [
            (
                "serine/threonine protein kinase",
                ["IPR050205", "IPR051681", "IPR030616"],
            ),
            ("rhoptry", ["IPR009864"]),
            ("rifin", ["IPR006373"]),
        ],
    )
    async def test_an_unnamed_phrase_is_unsettled_with_the_ranked_candidates(
        self, domains: list[VocabOption], phrase: str, first: list[str]
    ) -> None:
        stub = _answering([])

        got = await resolve_entry(
            domains, phrase, parameter=DOMAINS, about=ABOUT, arm="refuse", floor=0.5
        )

        assert got.how == "unsettled"
        assert got.value is None
        assert [c.value[:9] for c in got.candidates[: len(first)]] == first
        assert stub.sent == []


class TestTheChoiceArms:
    async def test_a_confident_choice_is_decided(
        self, domains: list[VocabOption]
    ) -> None:
        choice, _ = _recorded()
        stub = _answering([choice])

        got = await resolve_entry(
            domains,
            "protein kinase",
            parameter=DOMAINS,
            about=ABOUT,
            arm="choice",
            floor=0.5,
        )

        assert got.how == "decided"
        assert got.value == got.candidates[0].value == "IPR011009"
        assert got.confidence == 0.89
        assert len(got.candidates) == 254
        assert len(stub.sent) == 1

    async def test_a_choice_the_fit_doubts_is_unsettled(
        self, domains: list[VocabOption]
    ) -> None:
        choice, fit = _recorded()
        stub = _answering([choice, fit])

        got = await resolve_entry(
            domains,
            "protein kinase",
            parameter=DOMAINS,
            about=ABOUT,
            arm="choice_fit",
            floor=0.5,
        )

        assert got.how == "unsettled"
        assert got.value is None
        assert got.confidence == 0.31
        assert len(got.candidates) == 254
        assert len(stub.sent) == 2

    @pytest.mark.parametrize("arm", ["choice", "choice_fit"])
    async def test_none_fits_is_unsettled(
        self, domains: list[VocabOption], arm: Arm
    ) -> None:
        stub = _answering([_choosing("none_fits", 0.96)])

        got = await resolve_entry(
            domains, "rhoptry", parameter=DOMAINS, about=ABOUT, arm=arm, floor=0.5
        )

        assert got.how == "unsettled"
        assert got.candidates[0].value.startswith("IPR009864")
        assert len(stub.sent) == 1

    @pytest.mark.parametrize("arm", ["choice", "choice_fit"])
    async def test_no_answer_is_unsettled(
        self, domains: list[VocabOption], arm: Arm
    ) -> None:
        _answering([None])

        got = await resolve_entry(
            domains, "rhoptry", parameter=DOMAINS, about=ABOUT, arm=arm, floor=0.5
        )

        assert got.how == "unsettled"
        assert got.confidence is None

    async def test_a_choice_below_the_floor_is_unsettled(
        self, domains: list[VocabOption]
    ) -> None:
        _answering([_choosing("e0", 0.4)])

        got = await resolve_entry(
            domains, "rifin", parameter=DOMAINS, about=ABOUT, arm="choice", floor=0.5
        )

        assert got.how == "unsettled"
        assert got.confidence == 0.4

    @pytest.mark.parametrize("arm", ["refuse", "choice", "choice_fit"])
    async def test_an_exact_entry_sends_no_request(
        self, organisms: list[VocabOption], arm: Arm
    ) -> None:
        stub = _answering([])

        got = await resolve_entry(
            organisms,
            "Plasmodium falciparum 3D7",
            parameter="Organism",
            about=ABOUT,
            arm=arm,
            floor=0.5,
        )

        assert got.how == "exact"
        assert got.value == "Plasmodium falciparum 3D7"
        assert stub.sent == []


class TestTheRequest:
    def test_the_request_offers_every_ranked_entry_and_none_fits(
        self, organisms: list[VocabOption]
    ) -> None:
        ranked = rank_entries(organisms, "Pf3D7", 254)

        request = resolve_request(ABOUT, "Organism", "Pf3D7", ranked)

        question = request.questions[0]
        assert isinstance(question, ChoiceQuestion)
        offered = question.choices
        assert len(ranked) == 90
        assert [c.description for c in offered[:-1]] == [o.display for o in ranked]
        assert offered[0].value == "e0"
        assert offered[0].description == "Plasmodium falciparum 3D7"
        assert offered[-1].value == "none_fits"
        assert "Pf3D7" in request.input
        assert "Organism" in request.input
        assert "plasmodb" in request.input
        assert "message" not in request.input

    def test_the_message_is_part_of_the_input_when_there_is_one(
        self, organisms: list[VocabOption]
    ) -> None:
        about = ResolveContext(
            site_id="plasmodb", message="Genes up in Pf3D7 gametocytes"
        )

        request = resolve_request(
            about, "Organism", "Pf3D7", rank_entries(organisms, "Pf3D7", 5)
        )

        assert "Genes up in Pf3D7 gametocytes" in request.input

    async def test_the_choice_sent_is_the_request_built(
        self, organisms: list[VocabOption]
    ) -> None:
        stub = _answering([_choosing("e0", 0.97)])

        got = await resolve_entry(
            organisms,
            "Pf3D7",
            parameter="Organism",
            about=ABOUT,
            arm="choice",
            floor=0.5,
        )

        assert got.how == "decided"
        assert got.value == "Plasmodium falciparum 3D7"
        assert stub.sent == [
            resolve_request(ABOUT, "Organism", "Pf3D7", got.candidates)
        ]

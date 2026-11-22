"""A refusal's shown candidates lead with the entry a Decisions choice picks, and the pick never binds."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import JsonValue
from tests._support.filter_reads import FilterReadsDouble
from veupathdb.domain import SearchContext
from veupathdb.domain.parameters import (
    DECIDED_CANDIDATES,
    SHOWN_CANDIDATES,
    VocabularyEntryError,
    entries_or_refusal,
    flatten_vocab,
    rank_entries,
)
from veupathdb.testing import NEEDS_QA_RECORDING, needs_qa_recording
from veupathdb.testing.wdk_fixtures import load_recorded
from veupathdb.wdk import WDKParameter, WDKSearchResponse

from veupathdb_mcp.catalog import (
    ChoiceQuestion,
    DecisionRequest,
    DecisionResponse,
    ResolveContext,
    ordered_refusal,
    read_under_parents,
    resolve_params_with_intent,
    use_decisions_transport,
)
from veupathdb_mcp.catalog.param_dag import ParamFetcher
from veupathdb_mcp.catalog.param_intent import ParamIntent
from veupathdb_mcp.catalog.param_phyletic import (
    PhyleticListError,
    PhyleticUnresolvedProposal,
)

FIXTURES = Path(__file__).parent / "fixtures"
_HAGAI = "search_genes_by_metabolic_pathway_hagai"
_TAXON = "search_genes_by_taxon"
_SITE = ResolveContext(site_id="plasmodb")
_RECORDED = needs_qa_recording(f"wdk/{_HAGAI}.json", f"wdk/{_TAXON}.json")


def _exchange(name: str) -> tuple[DecisionRequest, DecisionResponse]:
    [exchange] = json.loads((FIXTURES / name).read_text())["exchanges"]
    return (
        DecisionRequest.model_validate(exchange["request"]),
        DecisionResponse.model_validate(exchange["response"]),
    )


class _Recorded:
    def __init__(self, request: DecisionRequest, response: DecisionResponse) -> None:
        self.request = request
        self.response = response
        self.sent: list[DecisionRequest] = []

    async def __call__(self, request: DecisionRequest) -> DecisionResponse | None:
        self.sent.append(request)
        return self.response if request == self.request else None


def _replaying(name: str) -> _Recorded:
    replay = _Recorded(*_exchange(name))
    use_decisions_transport(replay)
    return replay


def _answering(choice: str) -> None:
    async def send(request: DecisionRequest) -> DecisionResponse:
        del request
        return DecisionResponse.model_validate(
            {
                "answers": [
                    {
                        "type": "choice",
                        "name": "value",
                        "choice": choice,
                        "probabilities": [{"value": choice, "probability": 1.0}],
                        "confidence": 1.0,
                    }
                ]
            }
        )

    use_decisions_transport(send)


def _params(fixture: str) -> list[WDKParameter]:
    search = WDKSearchResponse.model_validate(load_recorded(fixture).json_body())
    return search.search_data.parameters or []


def _serving(fixture: str) -> ParamFetcher:
    declarations = _params(fixture)

    async def fetch_at(context: dict[str, str]) -> list[WDKParameter]:
        del context
        return declarations

    return fetch_at


async def _refused(
    fixture: str, stated: dict[str, JsonValue], about: ResolveContext
) -> VocabularyEntryError:
    with pytest.raises(VocabularyEntryError) as refused:
        await read_under_parents(
            _serving(fixture), stated, FilterReadsDouble(), about=about
        )
    return refused.value


def _shown(refusal: VocabularyEntryError) -> list[str]:
    [(_, resolution)] = refusal.faults
    assert resolution.value is None
    return [c.value for c in resolution.candidates]


def _ranked(fixture: str, name: str, phrase: str) -> list[str]:
    [param] = [p for p in _params(fixture) if p.name == name]
    options = flatten_vocab(param.vocabulary)
    return [c.value for c in rank_entries(options, phrase, DECIDED_CANDIDATES)]


@pytest.mark.skipif(_RECORDED, reason=NEEDS_QA_RECORDING)
class TestARefusalOfAStatedRead:
    async def test_the_picked_entry_leads_and_the_ranking_follows(self) -> None:
        replay = _replaying("decisions_plasmodb_hagai_citric_acid_cycle_order.json")
        about = ResolveContext(
            site_id="plasmodb", message="Genes in the citric acid cycle."
        )

        refusal = await _refused(
            _HAGAI, {"metabolic_pathway": "citric acid cycle"}, about
        )

        ranked = _ranked(_HAGAI, "metabolic_pathway", "citric acid cycle")
        shown = _shown(refusal)
        assert replay.sent == [replay.request]
        assert shown[0] == "Mitochondrial TCA cycle"
        assert "Mitochondrial TCA cycle" not in ranked[:SHOWN_CANDIDATES]
        assert shown[1:] == ranked[: SHOWN_CANDIDATES - 1]
        assert "Candidates: Mitochondrial TCA cycle," in str(refusal.detail)

    async def test_a_pick_already_first_keeps_the_ranking(self) -> None:
        replay = _replaying("decisions_plasmodb_taxon_pf3d7_order.json")

        refusal = await _refused(_TAXON, {"organism": ["Pf3D7"]}, _SITE)

        assert replay.sent == [replay.request]
        assert (
            _shown(refusal) == _ranked(_TAXON, "organism", "Pf3D7")[:SHOWN_CANDIDATES]
        )

    async def test_no_answer_keeps_the_ranking(self) -> None:
        refusal = await _refused(_TAXON, {"organism": ["Pf3D7"]}, _SITE)

        assert (
            _shown(refusal) == _ranked(_TAXON, "organism", "Pf3D7")[:SHOWN_CANDIDATES]
        )

    @pytest.mark.parametrize("choice", ["none_fits", "e999", "x"])
    async def test_an_answer_that_names_no_offered_entry_keeps_the_ranking(
        self, choice: str
    ) -> None:
        _answering(choice)

        refusal = await _refused(
            _HAGAI, {"metabolic_pathway": "citric acid cycle"}, _SITE
        )

        ranked = _ranked(_HAGAI, "metabolic_pathway", "citric acid cycle")
        assert _shown(refusal) == ranked[:SHOWN_CANDIDATES]

    async def test_a_certain_pick_still_binds_nothing(self) -> None:
        _answering("e0")

        refusal = await _refused(_TAXON, {"organism": ["Pf3D7"]}, _SITE)

        assert refusal.faults[0][1].how == "unsettled"


async def test_none_fits_keeps_the_ranking_of_the_interpro_refusal() -> None:
    replay = _replaying(
        "decisions_plasmodb_interpro_serine_threonine_kinase_order.json"
    )
    recorded: dict[str, Any] = json.loads(
        (FIXTURES / "plasmodb_3d7_interpro_vocabulary_half_off.json").read_text()
    )
    search = WDKSearchResponse.model_validate(recorded["response_json"])
    [param] = [
        p for p in search.search_data.parameters or [] if p.name == "domain_typeahead"
    ]
    phrase = "serine/threonine protein kinase"
    options = flatten_vocab(param.vocabulary)
    with pytest.raises(VocabularyEntryError) as refused:
        entries_or_refusal(param.name, options, [phrase])

    ordered = await ordered_refusal(refused.value, [param], _SITE)

    assert replay.sent == [replay.request]
    assert [c.value[:9] for c in ordered.faults[0][1].candidates[:3]] == [
        "IPR050205",
        "IPR051681",
        "IPR030616",
    ]


_ORTHOLOGS = "search_genes_by_ortholog_pattern"


@pytest.mark.skipif(
    needs_qa_recording(f"wdk/{_ORTHOLOGS}.json"), reason=NEEDS_QA_RECORDING
)
class TestAPhyleticRefusal:
    async def _nearest(self, about: ResolveContext | None) -> list[str]:
        with pytest.raises(PhyleticListError) as refused:
            await resolve_params_with_intent(
                fetch_at=_serving(_ORTHOLOGS),
                filter_reads=FilterReadsDouble(),
                intent=ParamIntent(),
                search=SearchContext(
                    "plasmodb", "transcript", "GenesByOrthologPattern"
                ),
                stated={"included_species": "Pf3D7"},
                about=about,
            )
        match refused.value.refused:
            case PhyleticUnresolvedProposal(nearest=nearest):
                return [entry.display for entry in nearest["included_species"]]
            case other:
                raise AssertionError(other)

    async def test_the_picked_species_leads_the_nearest_entries(self) -> None:
        replay = _replaying("decisions_orthomcl_phyletic_pf3d7_order.json")

        nearest = await self._nearest(ResolveContext(site_id="orthomcl"))

        assert replay.sent == [replay.request]
        assert nearest[0] == "Plasmodium falciparum 3D7"
        assert len(nearest) == SHOWN_CANDIDATES

    async def test_with_no_reader_the_ranking_stands(self) -> None:
        _replaying("decisions_orthomcl_phyletic_pf3d7_order.json")

        nearest = await self._nearest(None)

        assert nearest[0] == "delta-Proteobacteria"


_TWELVE = [f"Plasmodium strain {i}" for i in range(12)]


def _counting() -> list[DecisionRequest]:
    sent: list[DecisionRequest] = []

    async def send(request: DecisionRequest) -> DecisionResponse:
        sent.append(request)
        [question] = request.questions
        assert isinstance(question, ChoiceQuestion)
        last = question.choices[-2].value
        return DecisionResponse.model_validate(
            {
                "answers": [
                    {
                        "type": "choice",
                        "name": question.name,
                        "choice": last,
                        "probabilities": [{"value": last, "probability": 1.0}],
                        "confidence": 1.0,
                    }
                ]
            }
        )

    use_decisions_transport(send)
    return sent


@pytest.mark.skipif(_RECORDED, reason=NEEDS_QA_RECORDING)
async def test_only_the_first_shown_count_of_terms_ask_the_choice() -> None:
    sent = _counting()
    [param] = [p for p in _params(_TAXON) if p.name == "organism"]
    options = flatten_vocab(param.vocabulary)
    with pytest.raises(VocabularyEntryError) as refused:
        entries_or_refusal(param.name, options, _TWELVE)

    ordered = await ordered_refusal(refused.value, [param], _SITE)

    assert len(sent) == SHOWN_CANDIDATES
    asked = [r.input for r in sent]
    for phrase in _TWELVE[:SHOWN_CANDIDATES]:
        assert any(f'"{phrase}"' in text for text in asked)
    for (_, resolution), phrase in zip(
        ordered.faults[SHOWN_CANDIDATES:], _TWELVE[SHOWN_CANDIDATES:], strict=True
    ):
        plain = rank_entries(options, phrase, SHOWN_CANDIDATES)
        assert resolution.candidates == plain


@pytest.mark.skipif(
    needs_qa_recording(f"wdk/{_ORTHOLOGS}.json"), reason=NEEDS_QA_RECORDING
)
async def test_a_phyletic_refusal_asks_for_at_most_the_shown_count_of_terms() -> None:
    sent = _counting()

    with pytest.raises(PhyleticListError):
        await resolve_params_with_intent(
            fetch_at=_serving(_ORTHOLOGS),
            filter_reads=FilterReadsDouble(),
            intent=ParamIntent(),
            search=SearchContext("plasmodb", "transcript", "GenesByOrthologPattern"),
            stated={"included_species": ", ".join(_TWELVE)},
            about=ResolveContext(site_id="orthomcl"),
        )

    assert len(sent) == SHOWN_CANDIDATES

"""An over-representation test runs against one organism's genome. When the
result spans several organisms and no background was named, the service
refuses instead of testing whichever organism the WDK form lists first."""

from __future__ import annotations

import pytest
from veupathdb.domain.parameters.wdk_vocab import WDKVocabTerm
from veupathdb.domain.strategy.validation import StepValidation
from veupathdb.json_types import JSONObject
from veupathdb.wdk.client import VEuPathDBClient
from veupathdb.wdk.strategy_api.api import StrategyAPI
from veupathdb.wdk.wdk_models import (
    WDKStepAnalysisType,
    WDKStepAnalysisTypeResponse,
)
from veupathdb.wdk.wdk_parameters import WDKEnumParam, WDKNumberParam, WDKParameter

from veupathdb_mcp.wdk.enrichment import service
from veupathdb_mcp.wdk.enrichment.service import EnrichmentService
from veupathdb_mcp.wdk.enrichment.types import BackgroundSource

EIMERIA = "Eimeria falciformis Bayer Haberkorn 1970"
TOXO = "Toxoplasma gondii ME49"

_ROW: JSONObject = {
    "goId": "GO:0020035",
    "goTerm": "adhesion of symbiont to host",
    "bgdGenes": "12",
    "resultGenes": "3",
    "percentInResult": "25.0",
    "foldEnrich": "9.1",
    "oddsRatio": "12.0",
    "pValue": "0.0001",
    "benjamini": "0.002",
    "bonferroni": "0.005",
}


def _organism_param(organisms: list[str]) -> WDKEnumParam:
    """The form's organism parameter: WDK lists the organisms in the result and
    defaults to the first."""
    return WDKEnumParam(
        name="organism",
        type="single-pick-vocabulary",
        initial_display_value=organisms[0],
        vocabulary=[WDKVocabTerm.model_validate([o, o, None]) for o in organisms],
    )


class _Wdk:
    def __init__(self, organisms: list[str]) -> None:
        self.organisms = organisms
        self.analyses: list[tuple[str, JSONObject]] = []

    async def get_step_count(self, step_id: int, user_id: str | None = None) -> int:
        del step_id, user_id
        return 10

    async def get_analysis_type(
        self, step_id: int, analysis_type: str, user_id: str | None = None
    ) -> WDKStepAnalysisTypeResponse:
        del step_id, user_id
        params: list[WDKParameter] = [
            _organism_param(self.organisms),
            WDKNumberParam(name="pValueCutoff", initial_display_value="0.05"),
            WDKEnumParam(
                name="goAssociationsOntologies",
                type="single-pick-vocabulary",
                initial_display_value="Biological Process",
            ),
        ]
        return WDKStepAnalysisTypeResponse(
            search_data=WDKStepAnalysisType(
                name=analysis_type, display_name=analysis_type, parameters=params
            ),
            validation=StepValidation(level="DISPLAYABLE", is_valid=True),
        )

    async def run_step_analysis(
        self, *, step_id: int, analysis_type: str, parameters: JSONObject
    ) -> JSONObject:
        del step_id
        self.analyses.append((analysis_type, dict(parameters)))
        return {"resultData": [_ROW], "pvalueCutoff": "0.05"}


def _install(monkeypatch: pytest.MonkeyPatch, organisms: list[str]) -> _Wdk:
    fake = _Wdk(organisms)
    api = StrategyAPI(VEuPathDBClient("https://example.invalid/service"), "1")
    monkeypatch.setattr(api, "get_step_count", fake.get_step_count)
    monkeypatch.setattr(api, "get_analysis_type", fake.get_analysis_type)
    monkeypatch.setattr(api, "run_step_analysis", fake.run_step_analysis)
    monkeypatch.setattr(service, "get_strategy_api", lambda site_id: api)
    return fake


class TestAResultSpanningSeveralOrganisms:
    @pytest.mark.asyncio
    async def test_is_refused_and_names_every_organism(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        wdk = _install(monkeypatch, [EIMERIA, TOXO])

        results, errors = await EnrichmentService().run_batch(
            site_id="toxodb", analysis_types=["go_process"], step_id=440274393
        )

        assert wdk.analyses == []
        assert results[0].terms == []
        assert results[0].error is not None
        assert EIMERIA in results[0].error
        assert TOXO in results[0].error
        assert "2 organisms" in results[0].error
        assert errors == [f"go_process: {results[0].error}"]

    @pytest.mark.asyncio
    async def test_runs_against_the_named_background(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        wdk = _install(monkeypatch, [EIMERIA, TOXO])

        results, errors = await EnrichmentService(
            BackgroundSource(organism=TOXO)
        ).run_batch(site_id="toxodb", analysis_types=["go_process"], step_id=1)

        assert errors == []
        assert [a for a, _ in wdk.analyses] == ["go-enrichment"]
        assert wdk.analyses[0][1]["organism"] == f'["{TOXO}"]'
        assert results[0].terms[0].term_id == "GO:0020035"
        assert results[0].total_genes_analyzed == 10


class TestAResultOfOneOrganism:
    @pytest.mark.asyncio
    async def test_runs_with_the_forms_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        wdk = _install(monkeypatch, [TOXO])

        results, errors = await EnrichmentService().run_batch(
            site_id="toxodb", analysis_types=["go_process"], step_id=1
        )

        assert errors == []
        assert wdk.analyses[0][1]["organism"] == f'["{TOXO}"]'
        assert results[0].error is None
        assert len(results[0].terms) == 1

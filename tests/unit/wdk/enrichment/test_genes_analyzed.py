"""The analyzed count is the size of the set that went in, never a term's
background count.

``percentInResult`` is result genes over background genes: the GO plugin's own
column help reads "Of the genes in the background with this term, the percent
that are present in your result" (WDK-ANS-007). Dividing by it yields the
background, so the size comes from the step instead.
"""

from __future__ import annotations

import pytest
from veupathdb import JSONObject
from veupathdb.domain.strategy import StepValidation
from veupathdb.wdk import (
    StrategyAPI,
    VEuPathDBClient,
    WDKNumberParam,
    WDKStepAnalysisType,
    WDKStepAnalysisTypeResponse,
    WDKStringParam,
)

from veupathdb_mcp.wdk.enrichment import service
from veupathdb_mcp.wdk.enrichment.service import EnrichmentService

_GENE_SET_SIZE = 46
_TOP_TERM_BACKGROUND = 217


def _proteolysis_row() -> JSONObject:
    """The top row of a 46-gene set's GO:BP result, as measured on PlasmoDB."""
    link = f"<a href='?param.ds_gene_ids.idList=X&autoRun=1'>{_GENE_SET_SIZE}</a>"
    return {
        "goId": "GO:0006508",
        "goTerm": "proteolysis",
        "bgdGenes": str(_TOP_TERM_BACKGROUND),
        "resultGenes": link,
        "percentInResult": "21.2",
        "foldEnrich": "20.65",
        "oddsRatio": "30.1",
        "pValue": "1e-40",
        "benjamini": "1e-38",
        "bonferroni": "1e-37",
    }


def _analysis_payload() -> JSONObject:
    return {"resultData": [_proteolysis_row()], "pvalueCutoff": "0.05"}


async def _analysis_form(
    step_id: int, analysis_type: str, user_id: str | None = None
) -> WDKStepAnalysisTypeResponse:
    del step_id, analysis_type, user_id
    return WDKStepAnalysisTypeResponse(
        searchData=WDKStepAnalysisType(
            name="go-enrichment",
            displayName="GO Enrichment",
            parameters=[
                WDKStringParam(
                    name="organism",
                    display_name="Organism",
                    initial_display_value="Plasmodium falciparum 3D7",
                ),
                WDKNumberParam(
                    name="pValueCutoff",
                    display_name="P-value cutoff",
                    initial_display_value="0.05",
                ),
            ],
        ),
        validation=StepValidation(level="SEMANTIC", isValid=True),
    )


async def _run_analysis(**kwargs: object) -> JSONObject:
    del kwargs
    return _analysis_payload()


async def _step_count(step_id: int, user_id: str | None = None) -> int:
    del step_id, user_id
    return _GENE_SET_SIZE


class TestTheServiceReportsTheStepsOwnCount:
    @pytest.mark.asyncio
    async def test_a_46_gene_step_reports_46_analyzed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        api = StrategyAPI(VEuPathDBClient("https://example.invalid/service"), "1")
        monkeypatch.setattr(api, "get_analysis_type", _analysis_form)
        monkeypatch.setattr(api, "run_step_analysis", _run_analysis)
        monkeypatch.setattr(api, "get_step_count", _step_count)
        monkeypatch.setattr(service, "get_strategy_api", lambda site_id: api)

        results, errors = await EnrichmentService()._run_analyses_on_step(
            "plasmodb", 440117143, ["go_process"], []
        )

        assert errors == []
        assert [r.total_genes_analyzed for r in results] == [_GENE_SET_SIZE]
        assert results[0].terms[0].background_count == _TOP_TERM_BACKGROUND

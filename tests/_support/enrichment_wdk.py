"""The WDK calls the enrichment machinery makes, answered from recorded rows."""

from __future__ import annotations

import pytest
from veupathdb.domain.strategy.validation import StepValidation
from veupathdb.errors import WDKError
from veupathdb.json_types import JSONObject
from veupathdb.wdk.wdk_models import (
    NewStepSpec,
    WDKDatasetConfigIdList,
    WDKIdentifier,
    WDKStepAnalysisType,
    WDKStepAnalysisTypeResponse,
    WDKStepTree,
)
from veupathdb.wdk.wdk_parameters import (
    WDKEnumParam,
    WDKNumberParam,
    WDKParameter,
)

from veupathdb_mcp.wdk import gene_set_steps
from veupathdb_mcp.wdk.enrichment import service

_ANALYSIS_FAILED = "the analysis plugin refused"

ORGANISM = "Plasmodium falciparum 3D7"

_SHARED_STATS: JSONObject = {
    "bgdGenes": "120",
    "resultGenes": "3",
    "percentInResult": "12.5",
    "foldEnrich": "3.48",
    "oddsRatio": "4.12",
    "pValue": "0.0001",
    "benjamini": "0.002",
    "bonferroni": "0.005",
}

GO_ROW: JSONObject = {
    "goId": "GO:0004672",
    "goTerm": "protein kinase activity",
    **_SHARED_STATS,
}
PATHWAY_ROW: JSONObject = {
    "pathwayId": "kegg_pfa00010",
    "pathwayName": "Glycolysis / Gluconeogenesis",
    **_SHARED_STATS,
}
WORD_ROW: JSONObject = {
    "word": "kinase",
    "pathwayName": "protein kinase, putative",
    **_SHARED_STATS,
}


def _form(analysis_name: str) -> list[WDKParameter]:
    """The parameters an enrichment analysis form offers, with its defaults."""
    params: list[WDKParameter] = [
        WDKEnumParam(
            name="organism",
            type="single-pick-vocabulary",
            initial_display_value=ORGANISM,
        ),
        WDKNumberParam(name="pValueCutoff", initial_display_value="0.05"),
    ]
    if analysis_name == "go-enrichment":
        params.append(
            WDKEnumParam(
                name="goAssociationsOntologies",
                type="single-pick-vocabulary",
                initial_display_value="Biological Process",
            )
        )
    return params


class FakeStrategyAPI:
    """Answers the WDK calls the shared enrichment machinery makes."""

    def __init__(self) -> None:
        self.rows: dict[str, list[JSONObject]] = {}
        self.failing: set[str] = set()
        self.datasets: list[list[str]] = []
        self.steps: list[tuple[NewStepSpec, str]] = []
        self.strategies: list[int] = []
        self.deleted: list[int] = []
        self.analyses: list[tuple[str, JSONObject]] = []

    async def create_dataset(self, config: WDKDatasetConfigIdList) -> int:
        self.datasets.append(list(config.source_content.ids))
        return 4242

    async def create_step(self, spec: NewStepSpec, record_type: str) -> WDKIdentifier:
        self.steps.append((spec, record_type))
        return WDKIdentifier(id=101)

    async def create_strategy(
        self,
        *,
        step_tree: WDKStepTree,
        name: str,
        description: str | None = None,
        is_internal: bool = False,
    ) -> WDKIdentifier:
        del step_tree, name, description, is_internal
        self.strategies.append(202)
        return WDKIdentifier(id=202)

    async def delete_strategy(self, strategy_id: int) -> None:
        self.deleted.append(strategy_id)

    async def get_step_count(self, step_id: int, user_id: str | None = None) -> int:
        """The step holds the temporary dataset, so its count is the list's."""
        del step_id, user_id
        return len(self.datasets[-1]) if self.datasets else 0

    async def get_analysis_type(
        self, step_id: int, analysis_type: str
    ) -> WDKStepAnalysisTypeResponse:
        del step_id
        return WDKStepAnalysisTypeResponse(
            search_data=WDKStepAnalysisType(
                name=analysis_type,
                display_name=analysis_type,
                parameters=_form(analysis_type),
            ),
            validation=StepValidation(level="DISPLAYABLE", is_valid=True),
        )

    async def run_step_analysis(
        self, *, step_id: int, analysis_type: str, parameters: JSONObject
    ) -> JSONObject:
        del step_id
        self.analyses.append((analysis_type, dict(parameters)))
        if analysis_type in self.failing:
            raise WDKError(_ANALYSIS_FAILED, status=500)
        return {
            "resultData": self.rows.get(analysis_type, []),
            "downloadPath": "/download",
            "pvalueCutoff": "0.05",
        }


@pytest.fixture
def wdk(monkeypatch: pytest.MonkeyPatch) -> FakeStrategyAPI:
    """A site whose WDK calls this fake answers."""
    api = FakeStrategyAPI()
    monkeypatch.setattr(service, "get_strategy_api", lambda site_id: api)
    monkeypatch.setattr(gene_set_steps, "get_strategy_api", lambda site_id: api)
    return api

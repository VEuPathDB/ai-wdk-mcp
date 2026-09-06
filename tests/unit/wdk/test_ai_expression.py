"""Reading a site's own AI expression summary for one gene.

A gene with nothing cached is an answer, not a failure: the reporter never
generates, so the service reports what the site holds.
"""

from __future__ import annotations

import pytest
from pydantic import JsonValue
from veupathdb.errors import WDKError
from veupathdb.wdk.ai_expression import (
    AiExpressionReport,
    AiExpressionStatus,
)

from veupathdb_mcp.wdk import ai_expression
from veupathdb_mcp.wdk.ai_expression import (
    NO_SUMMARY_ON_THE_SITE,
    get_gene_expression_summary,
)

CACHED_GENE = "PF3D7_1133400"

_SUMMARY: JsonValue = {
    "headline": "Peak expression in late schizonts",
    "one_paragraph_summary": "<strong>Kelch13</strong> rises at schizogony.",
    "topics": [
        {
            "headline": "Asexual cycle",
            "one_sentence_summary": "Rises at schizogony.",
            "summaries": [
                {
                    "one_sentence_summary": "Upregulated.",
                    "notes": "",
                    "confidence": 4,
                    "biological_importance": 5,
                    "dataset_id": "DS_8ecf65d1b7",
                    "experiment_keywords": ["schizont"],
                }
            ],
        }
    ],
}


class _FakeClient:
    def __init__(self, report: JsonValue, refusal: WDKError | None = None) -> None:
        self._report = report
        self._refusal = refusal
        self.primary_keys: list[str] = []

    async def get_ai_expression_report(self, primary_keys: str) -> AiExpressionReport:
        self.primary_keys.append(primary_keys)
        if self._refusal is not None:
            raise self._refusal
        return AiExpressionReport.model_validate(self._report)


def _install(
    monkeypatch: pytest.MonkeyPatch,
    report: JsonValue,
    refusal: WDKError | None = None,
) -> _FakeClient:
    client = _FakeClient(report, refusal)
    monkeypatch.setattr(ai_expression, "get_wdk_client", lambda _site: client)
    return client


class TestThePrimaryKeyCarriesTheProjectId:
    async def test_the_site_project_id_is_appended(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _install(monkeypatch, {})

        await get_gene_expression_summary("plasmodb", CACHED_GENE)

        assert client.primary_keys == [f"{CACHED_GENE},PlasmoDB"]

    async def test_surrounding_space_is_dropped(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _install(monkeypatch, {})

        result = await get_gene_expression_summary("toxodb", "  TGME49_203310 ")

        assert client.primary_keys == ["TGME49_203310,ToxoDB"]
        assert result.gene_id == "TGME49_203310"


class TestAGeneWithASummary:
    async def test_the_summary_travels_with_the_site_and_the_gene(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install(
            monkeypatch,
            {
                CACHED_GENE: {
                    "resultStatus": "present",
                    "numExperiments": 41,
                    "numExperimentsComplete": 41,
                    "expressionSummary": _SUMMARY,
                }
            },
        )

        result = await get_gene_expression_summary("plasmodb", CACHED_GENE)

        assert result.site_id == "plasmodb"
        assert result.gene_id == CACHED_GENE
        assert result.result_status is AiExpressionStatus.PRESENT
        assert result.num_experiments == 41
        assert result.summary is not None
        assert result.summary.headline == "Peak expression in late schizonts"
        assert result.unavailable_reason is None


class TestAGeneWithoutASummary:
    async def test_an_incomplete_cache_reports_the_miss_sentence(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install(
            monkeypatch,
            {
                CACHED_GENE: {
                    "resultStatus": "experiments_incomplete",
                    "numExperiments": 41,
                    "numExperimentsComplete": 0,
                }
            },
        )

        result = await get_gene_expression_summary("plasmodb", CACHED_GENE)

        assert result.summary is None
        assert result.unavailable_reason == NO_SUMMARY_ON_THE_SITE
        assert result.result_status is AiExpressionStatus.EXPERIMENTS_INCOMPLETE
        assert result.num_experiments_complete == 0

    async def test_an_expired_summary_is_a_miss_and_not_a_summary(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install(
            monkeypatch,
            {
                CACHED_GENE: {
                    "resultStatus": "expired",
                    "numExperiments": 41,
                    "numExperimentsComplete": 41,
                }
            },
        )

        result = await get_gene_expression_summary("plasmodb", CACHED_GENE)

        assert result.result_status is AiExpressionStatus.EXPIRED
        assert result.unavailable_reason == NO_SUMMARY_ON_THE_SITE

    async def test_a_report_that_names_no_gene_is_a_miss(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install(monkeypatch, {})

        result = await get_gene_expression_summary("plasmodb", CACHED_GENE)

        assert result.result_status is AiExpressionStatus.MISSING
        assert result.unavailable_reason == NO_SUMMARY_ON_THE_SITE
        assert result.num_experiments == 0


class TestARefusalStaysAnError:
    async def test_a_wdk_refusal_reaches_the_caller(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install(monkeypatch, {}, WDKError("No Gene record found", status=422))

        with pytest.raises(WDKError):
            await get_gene_expression_summary("plasmodb", "NOT_A_GENE")

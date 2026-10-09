"""Reading a site's own AI expression summary for one gene.

A gene with nothing cached is an answer, not a failure: the reporter never
generates, so the service reports what the site holds.
"""

from __future__ import annotations

import pytest
from pydantic import JsonValue
from veupathdb.errors import WDKError
from veupathdb.testing import NEEDS_QA_RECORDING
from veupathdb.testing.wdk_fixtures import load_recorded
from veupathdb.wdk import AiExpressionReport, AiExpressionStatus

from veupathdb_mcp.wdk import ai_expression
from veupathdb_mcp.wdk.ai_expression import (
    NO_SUMMARY_ON_THE_SITE,
    get_gene_expression_summary,
)

SUMMARIZED_GENE = "PF3D7_0709000"
INCOMPLETE_GENE = "PF3D7_1133400"


def _recorded(name: str) -> JsonValue:
    return load_recorded(name).json_body()


COMPONENT_KEY = ["source_id", "project_id"]
PORTAL_KEY = ["source_id"]


class _FakeClient:
    def __init__(
        self,
        report: JsonValue,
        refusal: WDKError | None = None,
        key_columns: list[str] | None = None,
    ) -> None:
        self._report = report
        self._refusal = refusal
        self._key_columns = COMPONENT_KEY if key_columns is None else key_columns
        self.primary_keys: list[str] = []
        self.reads: list[str] = []

    async def get(self, path: str) -> JsonValue:
        self.reads.append(path)
        return {"urlSegment": "gene", "primaryKeyColumnRefs": list(self._key_columns)}

    async def get_ai_expression_report(self, primary_keys: str) -> AiExpressionReport:
        self.primary_keys.append(primary_keys)
        if self._refusal is not None:
            raise self._refusal
        return AiExpressionReport.model_validate(self._report)


@pytest.fixture(autouse=True)
def no_record_type_read_yet(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ai_expression, "_GENE_KEY_COLUMNS", {})


def _install(
    monkeypatch: pytest.MonkeyPatch,
    report: JsonValue,
    refusal: WDKError | None = None,
    key_columns: list[str] | None = None,
) -> _FakeClient:
    client = _FakeClient(report, refusal, key_columns)
    monkeypatch.setattr(ai_expression, "get_wdk_client", lambda _site: client)
    return client


class TestThePrimaryKeyFollowsTheGeneRecordColumns:
    async def test_the_site_project_id_is_appended(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _install(monkeypatch, {})

        await get_gene_expression_summary("plasmodb", INCOMPLETE_GENE)

        assert client.primary_keys == [f"{INCOMPLETE_GENE},PlasmoDB"]

    async def test_surrounding_space_is_dropped(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _install(monkeypatch, {})

        result = await get_gene_expression_summary("toxodb", "  TGME49_203310 ")

        assert client.primary_keys == ["TGME49_203310,ToxoDB"]
        assert result.gene_id == "TGME49_203310"

    async def test_a_record_keyed_by_its_source_id_alone_sends_the_id_alone(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _install(monkeypatch, {}, key_columns=PORTAL_KEY)

        await get_gene_expression_summary("veupathdb", INCOMPLETE_GENE)

        assert client.primary_keys == [INCOMPLETE_GENE]

    async def test_the_gene_record_type_is_read_once_per_site(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _install(monkeypatch, {})

        await get_gene_expression_summary("plasmodb", INCOMPLETE_GENE)
        await get_gene_expression_summary("plasmodb", SUMMARIZED_GENE)

        assert client.reads == ["/record-types/gene"]


@pytest.mark.skip(reason=NEEDS_QA_RECORDING)
class TestTheRecordedSummarizedGene:
    """The recorded body of a gene the site summarized."""

    async def test_the_summary_travels_with_the_site_and_the_gene(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install(monkeypatch, _recorded("ai_expression_summary_present"))

        result = await get_gene_expression_summary("plasmodb", SUMMARIZED_GENE)

        assert result.site_id == "plasmodb"
        assert result.gene_id == SUMMARIZED_GENE
        assert result.result_status is AiExpressionStatus.PRESENT
        assert result.summary is not None
        assert result.summary.headline == (
            "Ring-stage-peaking transcript with recurrent stage-specific "
            "antisense activity"
        )
        assert [topic.headline for topic in result.summary.topics] == [
            "Consistent cyclical peak at ring/early trophozoite stage across the IDC",
            "Ring-stage bias extends across the broader parasite life cycle",
            "Stage-restricted antisense transcription hotspots",
            "Other",
        ]
        assert result.unavailable_reason is None

    async def test_a_summarized_gene_carries_no_experiment_count(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install(monkeypatch, _recorded("ai_expression_summary_present"))

        result = await get_gene_expression_summary("plasmodb", SUMMARIZED_GENE)

        assert result.num_experiments is None
        assert result.num_experiments_complete is None

    async def test_the_site_states_the_summary_covers_every_experiment(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install(monkeypatch, _recorded("ai_expression_summary_present"))

        result = await get_gene_expression_summary("plasmodb", SUMMARIZED_GENE)

        assert result.based_on_incomplete_data is False

    async def test_every_summary_line_names_its_experiment_and_assay(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install(monkeypatch, _recorded("ai_expression_summary_present"))

        result = await get_gene_expression_summary("plasmodb", SUMMARIZED_GENE)

        assert result.summary is not None
        lines = [line for topic in result.summary.topics for line in topic.summaries]
        assert len(lines) == 41
        assert lines[0].experiment_name == (
            "Intraerythrocytic development cycle transcriptome (2018)"
        )
        assert lines[0].assay_type == "RNA-Seq"
        assert lines[0].dataset_id == "DS_ee861a9187"
        assert lines[0].confidence == 4
        assert lines[0].biological_importance == 4
        assert sorted({line.assay_type for line in lines}) == ["RNA-Seq", "array"]
        assert len({line.experiment_name for line in lines}) == 41


@pytest.mark.skip(reason=NEEDS_QA_RECORDING)
class TestTheRecordedGeneWithExperimentsOutstanding:
    """The recorded body of a gene whose experiments are not all summarized."""

    async def test_an_incomplete_cache_reports_the_miss_sentence(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install(monkeypatch, _recorded("ai_expression_experiments_incomplete"))

        result = await get_gene_expression_summary("plasmodb", INCOMPLETE_GENE)

        assert result.summary is None
        assert result.unavailable_reason == NO_SUMMARY_ON_THE_SITE
        assert result.result_status is AiExpressionStatus.EXPERIMENTS_INCOMPLETE

    async def test_the_counts_of_an_outstanding_gene_reach_the_caller(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install(monkeypatch, _recorded("ai_expression_experiments_incomplete"))

        result = await get_gene_expression_summary("plasmodb", INCOMPLETE_GENE)

        assert result.num_experiments == 41
        assert result.num_experiments_complete == 0

    async def test_a_body_that_omits_the_flag_states_nothing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install(monkeypatch, _recorded("ai_expression_experiments_incomplete"))

        result = await get_gene_expression_summary("plasmodb", INCOMPLETE_GENE)

        assert result.based_on_incomplete_data is None


class TestAGeneWithoutASummary:
    async def test_an_expired_summary_is_a_miss_and_not_a_summary(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install(
            monkeypatch,
            {
                INCOMPLETE_GENE: {
                    "resultStatus": "expired",
                    "numExperiments": 41,
                    "numExperimentsComplete": 41,
                }
            },
        )

        result = await get_gene_expression_summary("plasmodb", INCOMPLETE_GENE)

        assert result.result_status is AiExpressionStatus.EXPIRED
        assert result.unavailable_reason == NO_SUMMARY_ON_THE_SITE
        assert result.num_experiments == 41
        assert result.num_experiments_complete == 41

    async def test_a_report_that_names_no_gene_is_a_miss(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install(monkeypatch, {})

        result = await get_gene_expression_summary("plasmodb", INCOMPLETE_GENE)

        assert result.result_status is AiExpressionStatus.MISSING
        assert result.unavailable_reason == NO_SUMMARY_ON_THE_SITE
        assert result.num_experiments is None
        assert result.num_experiments_complete is None
        assert result.based_on_incomplete_data is None


class TestARefusalStaysAnError:
    async def test_a_wdk_refusal_reaches_the_caller(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install(monkeypatch, {}, WDKError("No Gene record found", status=422))

        with pytest.raises(WDKError):
            await get_gene_expression_summary("plasmodb", "NOT_A_GENE")

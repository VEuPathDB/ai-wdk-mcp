"""Tests for the step control-test service the verification worker calls."""

import pytest
from veupathdb.wdk import (
    WDKAnswer,
    WDKAnswerMeta,
    WDKFilterValue,
    WDKRecordInstance,
    WDKSearchConfig,
    WDKStep,
)

from veupathdb_mcp.controls import ControlTestResult, run_step_control_tests
from veupathdb_mcp.tool_payloads import ControlOutcome
from veupathdb_mcp.wdk.step_report_filters import representative_transcript_only


class _FakeStrategyAPI:
    def __init__(self, answer: WDKAnswer, record_class_name: str) -> None:
        self._answer = answer
        self._record_class_name = record_class_name
        self.calls: list[tuple[int, int]] = []
        self.view_filters: list[list[WDKFilterValue] | None] = []

    async def find_step(self, step_id: int) -> WDKStep:
        return WDKStep(
            id=step_id,
            search_name="GenesByMolecularWeight",
            search_config=WDKSearchConfig(),
            record_class_name=self._record_class_name,
        )

    async def get_step_answer(
        self,
        step_id: int,
        attributes: list[str] | None = None,
        pagination: dict[str, int] | None = None,
        *,
        view_filters: list[WDKFilterValue] | None = None,
    ) -> WDKAnswer:
        del attributes
        self.calls.append((step_id, (pagination or {})["numRecords"]))
        self.view_filters.append(view_filters)
        return self._answer


def _answer(*ids: str) -> WDKAnswer:
    return WDKAnswer(
        meta=WDKAnswerMeta(total_count=len(ids), response_count=len(ids)),
        records=[WDKRecordInstance(display_name=gene_id) for gene_id in ids],
    )


def _bind(
    monkeypatch: pytest.MonkeyPatch, record_class_name: str = "transcript"
) -> _FakeStrategyAPI:
    api = _FakeStrategyAPI(
        _answer("PF3D7_0100100", "PF3D7_0100200", "PF3D7_0100300"), record_class_name
    )
    monkeypatch.setattr(
        "veupathdb_mcp.controls.control_tests.get_strategy_api",
        lambda site_id: api,
    )
    return api


@pytest.fixture
def fake_results(monkeypatch: pytest.MonkeyPatch) -> _FakeStrategyAPI:
    return _bind(monkeypatch)


async def test_a_transcript_step_is_read_one_row_per_gene(
    fake_results: _FakeStrategyAPI,
) -> None:
    await run_step_control_tests(site_id="plasmodb", wdk_step_id=4242)

    assert fake_results.view_filters == [[representative_transcript_only()]]


async def test_a_gene_step_is_read_without_a_view_filter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = _bind(monkeypatch, "gene")

    await run_step_control_tests(site_id="plasmodb", wdk_step_id=4242)

    assert api.view_filters == [None]


async def test_positive_controls_report_recall(fake_results: _FakeStrategyAPI) -> None:
    result = await run_step_control_tests(
        site_id="plasmodb",
        wdk_step_id=4242,
        positive_controls=["PF3D7_0100100", "PF3D7_0100200", "PF3D7_9999999"],
    )
    assert isinstance(result, ControlTestResult)
    assert result.site_id == "plasmodb"
    assert result.target.step_id == 4242
    assert result.target.estimated_size == 3
    assert result.positive is not None
    assert result.positive.controls_count == 3
    assert result.positive.intersection_count == 2
    assert result.positive.recall == pytest.approx(2 / 3)
    assert result.positive.intersection_ids_sample == [
        "PF3D7_0100100",
        "PF3D7_0100200",
    ]
    assert result.positive.missing_ids_sample == ["PF3D7_9999999"]
    assert result.negative is None
    assert fake_results.calls == [(4242, 50000)]


async def test_negative_controls_report_false_positive_rate(
    fake_results: _FakeStrategyAPI,
) -> None:
    result = await run_step_control_tests(
        site_id="plasmodb",
        wdk_step_id=7,
        negative_controls=["PF3D7_0100300", "PF3D7_8888888"],
    )
    assert result.negative is not None
    assert result.negative.controls_count == 2
    assert result.negative.intersection_count == 1
    assert result.negative.false_positive_rate == pytest.approx(0.5)
    assert result.negative.intersection_ids_sample == ["PF3D7_0100300"]
    assert result.positive is None


async def test_no_controls_leaves_the_counts_unset(
    fake_results: _FakeStrategyAPI,
) -> None:
    result = await run_step_control_tests(site_id="plasmodb", wdk_step_id=1)

    assert result.positive is None
    assert result.negative is None
    assert result.target.step_id == 1
    assert result.target.estimated_size == 3
    assert result.target.search_name == ""


async def test_the_payload_layer_flattens_the_result(
    fake_results: _FakeStrategyAPI,
) -> None:
    """``ControlOutcome`` is the flat shape a host renders the runner's result as."""
    result = await run_step_control_tests(
        site_id="plasmodb",
        wdk_step_id=4242,
        positive_controls=["PF3D7_0100100", "PF3D7_9999999"],
        negative_controls=["PF3D7_0100300"],
    )

    outcome = ControlOutcome.model_validate(result)

    assert outcome.step_id == 4242
    assert outcome.estimated_size == 3
    assert outcome.positive_controls_count == 2
    assert outcome.positive_intersection == 1
    assert outcome.positive_recall == pytest.approx(0.5)
    assert outcome.positive_intersection_ids == ["PF3D7_0100100"]
    assert outcome.positive_missing_ids == ["PF3D7_9999999"]
    assert outcome.negative_controls_count == 1
    assert outcome.negative_intersection == 1
    assert outcome.negative_false_positive_rate == pytest.approx(1.0)
    assert outcome.negative_intersection_ids == ["PF3D7_0100300"]

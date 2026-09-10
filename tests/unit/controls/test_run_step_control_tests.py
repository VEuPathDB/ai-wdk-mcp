"""Tests for the step control-test service the verification worker calls."""

import pytest
from veupathdb.wdk.wdk_models import (
    WDKAnswer,
    WDKAnswerMeta,
    WDKRecordInstance,
)

from veupathdb_mcp.controls import ControlTestResult, run_step_control_tests
from veupathdb_mcp.tool_payloads import ControlOutcome


class _FakeResultsAPI:
    def __init__(self, answer: WDKAnswer) -> None:
        self._answer = answer
        self.calls: list[tuple[int, int]] = []

    async def get_step_preview(self, step_id: int, limit: int = 100) -> WDKAnswer:
        self.calls.append((step_id, limit))
        return self._answer


def _answer(*ids: str) -> WDKAnswer:
    return WDKAnswer(
        meta=WDKAnswerMeta(total_count=len(ids), response_count=len(ids)),
        records=[WDKRecordInstance(display_name=gene_id) for gene_id in ids],
    )


@pytest.fixture
def fake_results(monkeypatch: pytest.MonkeyPatch) -> _FakeResultsAPI:
    api = _FakeResultsAPI(_answer("PF3D7_0100100", "PF3D7_0100200", "PF3D7_0100300"))
    monkeypatch.setattr(
        "veupathdb_mcp.controls.control_tests.get_results_api",
        lambda site_id: api,
    )
    return api


async def test_positive_controls_report_recall(fake_results: _FakeResultsAPI) -> None:
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
    fake_results: _FakeResultsAPI,
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
    fake_results: _FakeResultsAPI,
) -> None:
    result = await run_step_control_tests(site_id="plasmodb", wdk_step_id=1)

    assert result.positive is None
    assert result.negative is None
    assert result.target.step_id == 1
    assert result.target.estimated_size == 3
    assert result.target.search_name == ""


async def test_the_payload_layer_flattens_the_result(
    fake_results: _FakeResultsAPI,
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

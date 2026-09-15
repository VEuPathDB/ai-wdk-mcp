"""One search counted through the anonymous report, and what it costs."""

from __future__ import annotations

import asyncio
import inspect
import time

import pytest
from veupathdb import JSONObject
from veupathdb.domain.parameters import ParamValue, StringValue
from veupathdb.errors import VEuPathDBError, VEuPathDBErrorCode
from veupathdb.wdk import WDKAnswer, WDKAnswerMeta, WDKSearchConfig

from veupathdb_mcp.wdk import count_search_answer, plan_counts


def _params() -> dict[str, ParamValue]:
    return {
        "text_expression": StringValue(value='"variant surface protein"'),
        "document_type": StringValue(value="gene"),
    }


class _Recorder:
    """Answers one report and records what was asked of the site."""

    def __init__(self, answer: int | Exception | None, delay: float = 0.0) -> None:
        self._answer = answer
        self._delay = delay
        self.search_configs: list[WDKSearchConfig] = []
        self.report_configs: list[JSONObject | None] = []

    async def run_search_report(
        self,
        record_type: str,
        search_name: str,
        search_config: WDKSearchConfig,
        report_config: JSONObject | None = None,
    ) -> WDKAnswer:
        del record_type, search_name
        self.search_configs.append(search_config)
        self.report_configs.append(report_config)
        if self._delay:
            await asyncio.sleep(self._delay)
        if isinstance(self._answer, Exception):
            raise self._answer
        return WDKAnswer(meta=WDKAnswerMeta(total_count=self._answer), records=[])


def _serve(
    monkeypatch: pytest.MonkeyPatch, answer: int | Exception | None, delay: float = 0.0
) -> _Recorder:
    recorder = _Recorder(answer, delay)
    monkeypatch.setattr(plan_counts, "get_wdk_client", lambda site_id: recorder)
    return recorder


async def test_the_count_comes_from_a_report_that_asks_for_no_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = _serve(monkeypatch, 3)

    count = await count_search_answer(
        "giardiadb", "transcript", "GenesByText", _params()
    )

    assert count == 3
    assert recorder.report_configs == [{"pagination": {"offset": 0, "numRecords": 0}}]


async def test_the_search_carries_the_parameters_on_the_wire(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = _serve(monkeypatch, 128)

    count = await count_search_answer(
        "piroplasmadb", "transcript", "GenesByText", _params()
    )

    assert count == 128
    assert dict(recorder.search_configs[0].parameters) == {
        "text_expression": '"variant surface protein"',
        "document_type": "gene",
    }


async def test_a_search_that_matches_nothing_reports_the_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _serve(monkeypatch, 0)

    count = await count_search_answer(
        "plasmodb", "transcript", "GenesByText", _params()
    )

    assert count == 0


async def test_a_read_the_site_refuses_reports_no_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    refusal = VEuPathDBError(VEuPathDBErrorCode.WDK_ERROR, "WDK is down", status=500)
    recorder = _serve(monkeypatch, refusal)

    count = await count_search_answer(
        "plasmodb", "transcript", "GenesByText", _params()
    )

    assert count is None
    assert len(recorder.report_configs) == 1


async def test_an_answer_that_publishes_no_count_reports_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = _serve(monkeypatch, None)

    count = await count_search_answer(
        "plasmodb", "transcript", "GenesByText", _params()
    )

    assert count is None
    assert len(recorder.report_configs) == 1


async def test_a_read_over_its_budget_reports_no_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _serve(monkeypatch, 9_667, delay=0.4)

    started = time.monotonic()
    count = await count_search_answer(
        "giardiadb", "transcript", "GenesByText", _params(), timeout_seconds=0.05
    )
    elapsed = time.monotonic() - started

    assert count is None
    assert elapsed < 0.3, "the caller does not wait out a read past its budget"


async def test_a_read_within_its_budget_answers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _serve(monkeypatch, 42, delay=0.05)

    count = await count_search_answer(
        "plasmodb", "transcript", "GenesByText", _params(), timeout_seconds=5.0
    )

    assert count == 42


async def test_a_read_with_no_stated_budget_is_not_cut_short(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _serve(monkeypatch, 9_667, delay=0.1)

    count = await count_search_answer(
        "giardiadb", "transcript", "GenesByText", _params()
    )

    assert count == 9_667


def test_the_budget_is_the_callers_to_state() -> None:
    """The library owns the mechanism; the host owns the number."""
    parameters = inspect.signature(count_search_answer).parameters

    assert list(parameters) == [
        "site_id",
        "record_type",
        "search_name",
        "parameters",
        "timeout_seconds",
    ]
    assert parameters["timeout_seconds"].default is None

"""What a report config asks for is what comes back.

WDK answers a report config literally. An omitted key is a request for
nothing, not a request for the default.
"""

from __future__ import annotations

from typing import Any

import pytest
from veupathdb.domain.wdk_values import WDKSortDirection
from veupathdb.wdk.client import VEuPathDBClient
from veupathdb.wdk.strategy_api.api import StrategyAPI
from veupathdb.wdk.wdk_models import WDKSortSpec

from veupathdb_mcp.wdk.step_results import StepResultsService

_ANSWER: dict[str, Any] = {
    "meta": {
        "totalCount": 19,
        "responseCount": 1,
        "recordClassName": "transcript",
        "attributes": [],
        "tables": [],
    },
    "records": [
        {
            "displayName": "PF3D7_0100100",
            "id": [{"name": "source_id", "value": "PF3D7_0100100"}],
            "recordClassName": "TranscriptRecordClasses.TranscriptRecordClass",
            "attributes": {},
        }
    ],
}

_EMPTY_PAGE: dict[str, Any] = {
    "meta": {"totalCount": 19, "responseCount": 0, "recordClassName": "transcript"},
    "records": [],
}


class _Recorder:
    """Captures the request body instead of reaching WDK."""

    def __init__(self, response: dict[str, Any]) -> None:
        self._response = response
        self.paths: list[str] = []
        self.bodies: list[dict[str, Any]] = []

    async def __call__(
        self, path: str, json: dict[str, Any] | None = None, **_: object
    ) -> Any:
        self.paths.append(path)
        self.bodies.append(json or {})
        return self._response

    @property
    def config(self) -> dict[str, Any]:
        return self.bodies[-1]["reportConfig"]


def _api(
    monkeypatch: pytest.MonkeyPatch, response: dict[str, Any] = _ANSWER
) -> tuple[StrategyAPI, _Recorder]:
    client = VEuPathDBClient("https://example.invalid/service")
    recorder = _Recorder(response)
    monkeypatch.setattr(client, "post", recorder)
    return StrategyAPI(client, user_id="1"), recorder


class TestAttributesAreOnlyWhatWeAskFor:
    async def test_named_attributes_reach_the_wire(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        api, sent = _api(monkeypatch)

        await api.get_step_records(9, attributes=["gene_id", "product"], user_id="1")

        assert sent.config["attributes"] == ["gene_id", "product"]

    async def test_asking_for_none_sends_no_attributes_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        api, sent = _api(monkeypatch)

        await api.get_step_records(9, user_id="1")

        assert "attributes" not in sent.config

    async def test_an_empty_list_is_the_same_as_asking_for_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        api, sent = _api(monkeypatch)

        await api.get_step_records(9, attributes=[], user_id="1")

        assert "attributes" not in sent.config

    async def test_identity_survives_an_attributeless_report(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Record identity is not an attribute, so an id-only preview is usable.
        api, _ = _api(monkeypatch)

        answer = await api.get_step_records(9, user_id="1")

        assert answer.records[0].id[0].value == "PF3D7_0100100"
        assert answer.records[0].attributes == {}

    async def test_tables_follow_the_same_rule(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        api, sent = _api(monkeypatch)

        await api.get_step_records(9, user_id="1")

        assert "tables" not in sent.config


class TestACountAsksForZeroRecords:
    async def test_the_count_page_is_exactly_zero_records(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A negative value would stream the whole answer instead.
        api, sent = _api(monkeypatch, _EMPTY_PAGE)

        await api.get_step_count(9, user_id="1")

        assert sent.config["pagination"] == {"offset": 0, "numRecords": 0}

    async def test_the_count_comes_from_meta_not_from_the_rows(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        api, _ = _api(monkeypatch, _EMPTY_PAGE)

        assert await api.get_step_count(9, user_id="1") == 19

    async def test_no_pagination_key_is_sent_when_none_is_asked_for(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Without the key WDK streams every record, so a caller must opt in.
        api, sent = _api(monkeypatch)

        await api.get_step_records(9, attributes=["gene_id"], user_id="1")

        assert "pagination" not in sent.config

    async def test_wdk_step_005_a_step_count_addresses_a_step_in_a_strategy(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = VEuPathDBClient("https://example.invalid/service")
        recorder = _Recorder(
            {"meta": {"totalCount": 132, "responseCount": 0}, "records": []}
        )

        async def get(path: str, **_: object) -> Any:
            del path
            return {"id": 4315616, "isGuest": False}

        monkeypatch.setattr(client, "get", get)
        monkeypatch.setattr(client, "post", recorder)

        assert await StrategyAPI(client).get_step_count(440085983) == 132
        assert recorder.paths == ["/users/4315616/steps/440085983/reports/standard"]


class TestOnlyTheJsonReporterHonoursThePage:
    async def test_records_go_through_the_standard_reporter(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        api, sent = _api(monkeypatch)

        await api.get_step_records(9, user_id="1")

        assert sent.paths[-1].endswith("/reports/standard")

    async def test_the_service_always_bounds_its_page(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        api, sent = _api(monkeypatch)
        service = StepResultsService(api, step_id=9, record_type="transcript")

        await service.get_records(offset=40, limit=20)

        assert sent.config["pagination"] == {"offset": 40, "numRecords": 20}

    async def test_sorting_reaches_the_reporter_that_applies_it(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        api, sent = _api(monkeypatch)

        await api.get_step_records(
            9,
            sorting=[WDKSortSpec(attribute_name="gene_id", direction="DESC")],
            user_id="1",
        )

        assert sent.config["sorting"] == [
            {"attributeName": "gene_id", "direction": "DESC"}
        ]
        assert sent.paths[-1].endswith("/reports/standard")

    async def test_the_service_sort_direction_is_carried(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        api, sent = _api(monkeypatch)
        service = StepResultsService(api, step_id=9, record_type="transcript")
        direction: WDKSortDirection = "DESC"

        await service.get_records(sort="product", direction=direction)

        assert sent.config["sorting"][0]["direction"] == "DESC"


class TestTheStepReportEndpointTakesOnlyAReportConfig:
    """The unpersisted report endpoint needs a searchConfig; this one does not.

    A step already carries its own search config, so sending one here is at
    best redundant and at worst a second, conflicting spec.
    """

    async def test_no_search_config_is_sent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        api, sent = _api(monkeypatch)

        await api.get_step_records(9, attributes=["gene_id"], user_id="1")

        assert "searchConfig" not in sent.bodies[-1]

    async def test_the_report_config_is_the_whole_body(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        api, sent = _api(monkeypatch)

        await api.get_step_records(9, attributes=["gene_id"], user_id="1")

        assert list(sent.bodies[-1]) == ["reportConfig"]

    async def test_a_count_sends_the_same_shape(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        api, sent = _api(monkeypatch, _EMPTY_PAGE)

        await api.get_step_count(9, user_id="1")

        assert list(sent.bodies[-1]) == ["reportConfig"]

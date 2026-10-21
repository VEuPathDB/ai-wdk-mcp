"""A step's ids are read up to the limit the caller passes, and a larger step is refused."""

from __future__ import annotations

from typing import Any

import pytest
from tests._support.step_report_wire import ReportWire, wire_api
from veupathdb.errors import ValidationError, WDKError
from veupathdb.wdk import StrategyAPI, VEuPathDBClient

from veupathdb_mcp.wdk import (
    GeneSetWdkContext,
    StepTooLargeError,
    fetch_gene_ids_from_step,
    gene_set_steps,
    resolve_wdk_context,
)

STEP_ID = 9
STRATEGY_ID = 70


def _page(size: int) -> dict[str, Any]:
    return {
        "meta": {
            "totalCount": size,
            "responseCount": size,
            "recordClassName": "sequence",
            "attributes": [],
            "tables": [],
        },
        "records": [
            {
                "displayName": f"pfal|PF3D7_{index:07d}-p1",
                "id": [{"name": "full_id", "value": f"pfal|PF3D7_{index:07d}-p1"}],
                "attributes": {},
            }
            for index in range(size)
        ],
    }


def _pagination(wire: ReportWire) -> list[dict[str, int]]:
    return [body["reportConfig"]["pagination"] for body in wire.bodies]


async def test_a_step_within_the_limit_asks_for_one_record_more(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api, wire = wire_api(monkeypatch, "sequence", [_page(2)])

    ids = await fetch_gene_ids_from_step(api, step_id=STEP_ID, limit=2)

    assert ids == ["pfal|PF3D7_0000000-p1", "pfal|PF3D7_0000001-p1"]
    assert _pagination(wire) == [{"offset": 0, "numRecords": 3}]


async def test_a_step_past_the_limit_is_refused_naming_the_step_and_the_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api, wire = wire_api(monkeypatch, "sequence", [_page(3)])

    with pytest.raises(StepTooLargeError, match=r"step 9 holds more than 2 records"):
        await fetch_gene_ids_from_step(api, step_id=STEP_ID, limit=2)
    assert _pagination(wire) == [{"offset": 0, "numRecords": 3}]


def test_the_refusal_is_a_validation_error_that_keeps_the_step_and_the_limit() -> None:
    refusal = StepTooLargeError(STEP_ID, 2)

    assert isinstance(refusal, ValidationError)
    assert (refusal.step_id, refusal.limit, refusal.status) == (STEP_ID, 2, 422)


async def test_a_record_without_an_id_still_counts_toward_the_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = _page(3)
    page["records"][1]["id"] = []
    api, _ = wire_api(monkeypatch, "sequence", [page])

    with pytest.raises(StepTooLargeError):
        await fetch_gene_ids_from_step(api, step_id=STEP_ID, limit=2)


@pytest.mark.parametrize("limit", [0, -1])
async def test_a_limit_below_one_sends_no_request(
    monkeypatch: pytest.MonkeyPatch, limit: int
) -> None:
    api, wire = wire_api(monkeypatch, "sequence", [_page(1)])

    with pytest.raises(ValueError, match="at least 1"):
        await fetch_gene_ids_from_step(api, step_id=STEP_ID, limit=limit)
    assert wire.bodies == []


class _StrategyWire(ReportWire):
    def __init__(
        self, pages: list[dict[str, Any]], refusal: WDKError | None = None
    ) -> None:
        super().__init__("sequence", pages)
        self.paths: list[str] = []
        self._refusal = refusal

    async def get(self, path: str, **kwargs: object) -> Any:
        self.paths.append(path)
        if path.endswith(f"/strategies/{STRATEGY_ID}"):
            if self._refusal is not None:
                raise self._refusal
            return {
                "strategyId": STRATEGY_ID,
                "name": "proteins",
                "rootStepId": STEP_ID,
                "stepTree": {"stepId": STEP_ID},
                "steps": {},
            }
        return await super().get(path, **kwargs)

    async def post(
        self, path: str, json: dict[str, Any] | None = None, **kwargs: object
    ) -> Any:
        self.paths.append(path)
        if self._refusal is not None:
            raise self._refusal
        return await super().post(path, json, **kwargs)


def _strategy_wire(
    monkeypatch: pytest.MonkeyPatch, size: int, refusal: WDKError | None = None
) -> _StrategyWire:
    client = VEuPathDBClient("https://example.invalid/service")
    wire = _StrategyWire([_page(size)], refusal)
    monkeypatch.setattr(client, "get", wire.get)
    monkeypatch.setattr(client, "post", wire.post)
    api = StrategyAPI(client, user_id="1")
    monkeypatch.setattr(gene_set_steps, "get_strategy_api", lambda site_id: api)
    return wire


def _strategy_context() -> GeneSetWdkContext:
    return GeneSetWdkContext(wdk_strategy_id=STRATEGY_ID, search_name="ByIdList")


async def test_a_strategy_read_passes_the_callers_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wire = _strategy_wire(monkeypatch, 2)

    ids, ctx, _ = await resolve_wdk_context(
        "orthomcl", [], _strategy_context(), limit=5
    )

    assert (len(ids), ctx.wdk_step_id) == (2, STEP_ID)
    assert _pagination(wire) == [{"offset": 0, "numRecords": 6}]


async def test_a_strategy_past_the_limit_is_refused_not_read_as_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wire = _strategy_wire(monkeypatch, 3)

    with pytest.raises(StepTooLargeError, match=r"step 9 holds more than 2 records"):
        await resolve_wdk_context("orthomcl", [], _strategy_context(), limit=2)
    assert _pagination(wire) == [{"offset": 0, "numRecords": 3}]


async def test_given_ids_send_no_request(monkeypatch: pytest.MonkeyPatch) -> None:
    wire = _strategy_wire(monkeypatch, 3)

    ids, _, _ = await resolve_wdk_context(
        "orthomcl", ["PF3D7_0100100"], _strategy_context(), limit=2
    )

    assert ids == ["PF3D7_0100100"]
    assert wire.bodies == []


@pytest.mark.parametrize("ids", [[], ["PF3D7_0100100"]])
async def test_a_limit_below_one_is_refused_before_any_request(
    monkeypatch: pytest.MonkeyPatch, ids: list[str]
) -> None:
    wire = _strategy_wire(monkeypatch, 1)

    with pytest.raises(ValueError, match="at least 1"):
        await resolve_wdk_context("orthomcl", ids, _strategy_context(), limit=0)
    assert wire.paths == []


@pytest.mark.parametrize("step_id", [None, STEP_ID])
async def test_a_site_refusal_is_raised_not_read_as_an_empty_step(
    monkeypatch: pytest.MonkeyPatch, step_id: int | None
) -> None:
    _strategy_wire(monkeypatch, 1, WDKError("step report failed", status=502))
    ctx = GeneSetWdkContext(wdk_strategy_id=STRATEGY_ID, wdk_step_id=step_id)

    with pytest.raises(WDKError, match="step report failed"):
        await resolve_wdk_context("orthomcl", [], ctx, limit=5)

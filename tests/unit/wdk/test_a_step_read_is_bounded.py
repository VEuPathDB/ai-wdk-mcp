"""A step's ids are read up to the limit the caller passes, and a larger step is refused."""

from __future__ import annotations

from typing import Any

import pytest
from tests._support.step_report_wire import ReportWire, wire_api
from veupathdb.errors import ValidationError

from veupathdb_mcp.wdk import StepTooLargeError, fetch_gene_ids_from_step

STEP_ID = 9


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

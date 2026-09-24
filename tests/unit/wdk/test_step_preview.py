from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from tests._support.step_report_wire import ReportWire, wire_api
from veupathdb.errors import WDKError
from veupathdb.wdk import (
    WDKAnswer,
    WDKAnswerMeta,
    WDKRecordInstance,
)

from veupathdb_mcp.tools.user_tools import get_step_sample_records
from veupathdb_mcp.wdk import step_preview
from veupathdb_mcp.wdk.step_preview import step_sample_records

_GENE_ATTRS = ["gene_product", "gene_name", "organism"]
_ATTRIBUTE_MISSING = "attribute 'gene_product' not found"
_NOT_IN_A_STRATEGY = "step 5 is not part of a strategy"


def _answer(records: list[WDKRecordInstance], attributes: list[str]) -> WDKAnswer:
    return WDKAnswer(
        meta=WDKAnswerMeta(
            total_count=len(records),
            record_class_name="transcript",
            attributes=attributes,
        ),
        records=records,
    )


class _FakeStrategyAPI:
    """``get_step_answer`` succeeds only WITHOUT attributes - simulating a
    record class that rejects the gene attributes."""

    def __init__(self, records: list[WDKRecordInstance] | None = None) -> None:
        self.calls: list[list[str] | None] = []
        self._records = records

    async def get_step_answer(
        self,
        step_id: int,
        attributes: list[str] | None = None,
        pagination: dict[str, int] | None = None,
    ) -> WDKAnswer:
        del step_id, pagination
        self.calls.append(attributes)
        if attributes and self._records is None:
            raise WDKError(_ATTRIBUTE_MISSING)
        if self._records is not None:
            return _answer(self._records, attributes or [])
        return _answer([WDKRecordInstance(display_name="x1")], [])


def _bind(monkeypatch: pytest.MonkeyPatch, api: _FakeStrategyAPI) -> None:
    monkeypatch.setattr(step_preview, "get_strategy_api", lambda site_id: api)


async def test_html_is_stripped_from_the_attribute_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # WDK returns organism wrapped in <i>...</i>; the read must surface a clean
    # value alongside the id + product name.
    api = _FakeStrategyAPI(
        [
            WDKRecordInstance(
                display_name="PF3D7_0610600",
                attributes={
                    "gene_product": "calcium-dependent protein kinase 2",
                    "gene_name": "CDPK2",
                    "organism": "<i>Plasmodium falciparum 3D7</i>",
                },
            ),
        ],
    )
    _bind(monkeypatch, api)

    result = await step_sample_records(
        "plasmodb",
        123,
        limit=5,
        attributes=_GENE_ATTRS,
    )

    assert result.step_id == 123
    assert result.total_count == 1
    assert result.attributes == _GENE_ATTRS
    assert result.records[0] == {
        "id": "PF3D7_0610600",
        "gene_product": "calcium-dependent protein kinase 2",
        "gene_name": "CDPK2",
        "organism": "Plasmodium falciparum 3D7",
    }


async def test_a_rejected_attribute_set_falls_back_to_an_id_only_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = _FakeStrategyAPI()
    _bind(monkeypatch, api)

    result = await step_sample_records(
        "plasmodb",
        5,
        limit=3,
        attributes=_GENE_ATTRS,
    )

    assert api.calls == [_GENE_ATTRS, None]  # tried enriched, then id-only
    assert result.records == [{"id": "x1"}]


async def test_a_refused_id_only_read_reaches_the_caller(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Refusing(_FakeStrategyAPI):
        async def get_step_answer(
            self,
            step_id: int,
            attributes: list[str] | None = None,
            pagination: dict[str, int] | None = None,
        ) -> WDKAnswer:
            del step_id, attributes, pagination
            raise WDKError(_NOT_IN_A_STRATEGY)

    _bind(monkeypatch, _Refusing())

    with pytest.raises(WDKError, match="not part of a strategy"):
        await step_sample_records("plasmodb", 5, limit=3, attributes=_GENE_ATTRS)


_RECORDED_PAGE = (
    Path(__file__).parent / "fixtures" / "transcript_page_with_repeated_genes.json"
)
_FIRST_EIGHT_GENES = [
    "PF3D7_0612400",
    "PF3D7_0612500",
    "PF3D7_0612600",
    "PF3D7_0612700",
    "PF3D7_0612800",
    "PF3D7_0612900",
    "PF3D7_0613000",
    "PF3D7_0613100",
]


def _recorded_page() -> dict[str, Any]:
    body: dict[str, Any] = json.loads(_RECORDED_PAGE.read_text())["body"]
    return body


def _transcript(gene: str, transcript: int) -> dict[str, Any]:
    return {
        "displayName": gene,
        "id": [
            {"name": "gene_source_id", "value": gene},
            {"name": "source_id", "value": f"{gene}.{transcript}"},
            {"name": "project_id", "value": "PlasmoDB"},
        ],
        "attributes": {},
    }


def _page(rows: list[dict[str, Any]], *, genes: int) -> dict[str, Any]:
    return {
        "meta": {
            "totalCount": genes + 10,
            "responseCount": len(rows),
            "displayTotalCount": genes,
            "viewTotalCount": genes + 10,
            "displayViewTotalCount": genes,
            "recordClassName": "transcript",
            "attributes": [],
            "tables": [],
        },
        "records": rows,
    }


def _bind_wire(
    monkeypatch: pytest.MonkeyPatch, pages: list[dict[str, Any]]
) -> ReportWire:
    api, wire = wire_api(monkeypatch, "transcript", pages)
    monkeypatch.setattr(step_preview, "get_strategy_api", lambda site_id: api)
    return wire


class TestASampleIsOneRowPerGene:
    async def test_the_first_row_of_each_gene_is_kept_in_the_order_seen(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        wire = _bind_wire(monkeypatch, [_recorded_page()])

        result = await step_sample_records(
            "plasmodb", 9, limit=8, attributes=_GENE_ATTRS
        )

        assert [row["id"] for row in result.records] == _FIRST_EIGHT_GENES
        assert result.total_count == 5720
        assert (
            result.records[6]["gene_product"]
            == (_recorded_page()["records"][6]["attributes"]["gene_product"])
        )
        assert result.records[0]["organism"] == "Plasmodium falciparum 3D7"
        (body,) = wire.bodies
        assert "viewFilters" not in body
        assert body["reportConfig"]["pagination"] == {"offset": 0, "numRecords": 32}
        assert body["reportConfig"]["attributes"] == _GENE_ATTRS

    async def test_a_page_short_of_distinct_genes_reads_one_more_page(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        first = [_transcript("PF3D7_0100100", n) for n in range(1, 9)]
        second = [
            _transcript("PF3D7_0100100", 9),
            _transcript("PF3D7_0100200", 1),
            _transcript("PF3D7_0100300", 1),
        ]
        wire = _bind_wire(monkeypatch, [_page(first, genes=3), _page(second, genes=3)])

        result = await step_sample_records("plasmodb", 9, limit=2)

        assert [row["id"] for row in result.records] == [
            "PF3D7_0100100",
            "PF3D7_0100200",
        ]
        assert [body["reportConfig"]["pagination"] for body in wire.bodies] == [
            {"offset": 0, "numRecords": 8},
            {"offset": 8, "numRecords": 8},
        ]
        assert all("viewFilters" not in body for body in wire.bodies)

    async def test_a_limit_past_the_gene_count_still_reads_the_next_page(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        first = [_transcript("PF3D7_0100100", n) for n in range(1, 4)]
        second = [_transcript("PF3D7_0100200", 1)]
        wire = _bind_wire(monkeypatch, [_page(first, genes=2), _page(second, genes=2)])

        result = await step_sample_records("plasmodb", 9, limit=5)

        assert [row["id"] for row in result.records] == [
            "PF3D7_0100100",
            "PF3D7_0100200",
        ]
        assert len(wire.bodies) == 2

    async def test_a_page_that_holds_every_gene_reads_no_more(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        rows = [_transcript("PF3D7_0100100", n) for n in range(1, 4)]
        wire = _bind_wire(monkeypatch, [_page(rows, genes=1)])

        result = await step_sample_records("plasmodb", 9, limit=2)

        assert [row["id"] for row in result.records] == ["PF3D7_0100100"]
        assert len(wire.bodies) == 1

    async def test_the_served_sample_is_the_same_gene_level_read(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        wire = _bind_wire(monkeypatch, [_recorded_page()])

        answer = await get_step_sample_records("plasmodb", 9, "transcript", limit=8)

        assert [record.display_name for record in answer.records] == (
            _FIRST_EIGHT_GENES
        )
        assert answer.meta.response_count == 8
        (body,) = wire.bodies
        assert "viewFilters" not in body
        assert body["reportConfig"]["attributes"] == _GENE_ATTRS

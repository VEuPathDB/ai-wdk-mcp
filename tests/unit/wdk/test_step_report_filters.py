"""A step report on a transcript step pages one row per gene."""

from __future__ import annotations

from typing import Any

import pytest
from tests._support.step_report_wire import (
    REPRESENTATIVE_TRANSCRIPT_ONLY_WIRE,
    wire_api,
)
from veupathdb.wdk import WDKFilterValue

from veupathdb_mcp.wdk import step_preview
from veupathdb_mcp.wdk.gene_set_steps import fetch_gene_ids_from_step
from veupathdb_mcp.wdk.step_preview import step_sample_records
from veupathdb_mcp.wdk.step_report_filters import (
    representative_transcript_only,
    view_filters_for,
)
from veupathdb_mcp.wdk.step_results import StepResultsService


def test_a_transcript_step_reads_the_representative_transcript_only() -> None:
    assert view_filters_for("transcript") == [
        WDKFilterValue(name="representativeTranscriptOnly", value={})
    ]
    assert view_filters_for("transcript") == [representative_transcript_only()]


@pytest.mark.parametrize("record_type", ["gene", "dataset", None])
def test_any_other_record_type_reads_every_row(record_type: str | None) -> None:
    assert view_filters_for(record_type) is None


def _last(bodies: list[dict[str, Any]]) -> dict[str, Any]:
    return bodies[-1]


class TestStepResultsServicePagesGenes:
    async def test_a_transcript_page_sends_the_view_filter_beside_the_config(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        api, wire = wire_api(monkeypatch, "transcript")
        service = StepResultsService(api, step_id=9, record_type="transcript")

        await service.get_records(offset=50, limit=50)

        body = _last(wire.bodies)
        assert body["viewFilters"] == REPRESENTATIVE_TRANSCRIPT_ONLY_WIRE
        assert body["reportConfig"]["pagination"] == {"offset": 50, "numRecords": 50}

    async def test_a_gene_page_sends_no_view_filter(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        api, wire = wire_api(monkeypatch, "gene")
        service = StepResultsService(api, step_id=9, record_type="gene")

        await service.get_records(offset=0, limit=50)

        assert "viewFilters" not in _last(wire.bodies)


class TestGeneIdsOfAStepAreOnePerGene:
    async def test_a_transcript_step_sends_the_view_filter(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        api, wire = wire_api(monkeypatch, "transcript")

        ids = await fetch_gene_ids_from_step(api, step_id=9)

        assert ids == ["PF3D7_0100100"]
        assert _last(wire.bodies)["viewFilters"] == REPRESENTATIVE_TRANSCRIPT_ONLY_WIRE

    async def test_a_gene_step_sends_no_view_filter(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        api, wire = wire_api(monkeypatch, "gene")

        await fetch_gene_ids_from_step(api, step_id=9, limit=10)

        assert "viewFilters" not in _last(wire.bodies)


class TestASamplePreviewIsOnePerGene:
    async def test_a_transcript_step_sends_the_view_filter(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        api, wire = wire_api(monkeypatch, "transcript")
        monkeypatch.setattr(step_preview, "get_strategy_api", lambda site_id: api)

        await step_sample_records("plasmodb", 9, limit=5)

        assert _last(wire.bodies)["viewFilters"] == REPRESENTATIVE_TRANSCRIPT_ONLY_WIRE

    async def test_a_gene_step_sends_no_view_filter(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        api, wire = wire_api(monkeypatch, "gene")
        monkeypatch.setattr(step_preview, "get_strategy_api", lambda site_id: api)

        await step_sample_records("plasmodb", 9, limit=5)

        assert "viewFilters" not in _last(wire.bodies)

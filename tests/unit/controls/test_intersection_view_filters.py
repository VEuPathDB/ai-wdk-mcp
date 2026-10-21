"""The identifiers of a control intersection are read one row per gene."""

from typing import Any

import pytest
from tests._support.control_run_wdk import RunFakeAPI, patch_control_run
from veupathdb.domain.strategy import CombineOp

from veupathdb_mcp.controls import run_positive_negative_controls
from veupathdb_mcp.controls.control_types import IntersectionConfig
from veupathdb_mcp.wdk.step_report_filters import representative_transcript_only


def _config() -> IntersectionConfig:
    return IntersectionConfig(
        site_id="plasmodb",
        record_type="transcript",
        target_search_name="GenesByMolecularWeight",
        target_parameters={},
        controls_search_name="GeneByLocusTag",
        controls_param_name="ds_gene_ids",
    )


async def test_a_transcript_intersection_reads_the_representative_transcript(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = patch_control_run(monkeypatch, RunFakeAPI())

    await run_positive_negative_controls(_config(), positive_controls=["PF3D7_0100100"])

    assert api.answer_view_filters == [[representative_transcript_only()]]


async def test_a_gene_intersection_reads_every_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = patch_control_run(monkeypatch, RunFakeAPI(), record_type="gene")

    await run_positive_negative_controls(_config(), positive_controls=["PF3D7_0100100"])

    assert api.answer_view_filters == [None]


async def test_the_controls_are_always_intersected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = patch_control_run(monkeypatch, RunFakeAPI())

    await run_positive_negative_controls(_config(), positive_controls=["PF3D7_0100100"])

    assert [combine.boolean_operator for combine in api.combines] == [
        CombineOp.INTERSECT
    ]


def test_no_operator_that_reaches_past_the_controls_can_be_asked_for() -> None:
    fields: dict[str, Any] = {
        "site_id": "plasmodb",
        "record_type": "transcript",
        "target_search_name": "GenesByMolecularWeight",
        "target_parameters": {},
        "controls_search_name": "GeneByLocusTag",
        "controls_param_name": "ds_gene_ids",
        "boolean_operator": CombineOp.UNION,
    }

    with pytest.raises(TypeError, match="boolean_operator"):
        IntersectionConfig(**fields)

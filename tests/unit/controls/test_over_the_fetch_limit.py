"""A control set larger than the fetch limit reports a count and no identifiers."""

from typing import Any

import pytest
from tests._support.control_run_wdk import RunFakeAPI, patch_control_run

from veupathdb_mcp.controls import run_positive_negative_controls
from veupathdb_mcp.controls.control_types import IntersectionConfig

OVER_THE_LIMIT = [f"PF3D7_{i:07d}" for i in range(501)]


def _config(**kwargs: Any) -> IntersectionConfig:
    return IntersectionConfig(
        site_id="plasmodb",
        record_type="transcript",
        target_search_name="GenesByMolecularWeight",
        target_parameters={},
        controls_search_name="GeneByLocusTag",
        controls_param_name="ds_gene_ids",
        **kwargs,
    )


@pytest.fixture
def run_api(monkeypatch: pytest.MonkeyPatch) -> RunFakeAPI:
    return patch_control_run(monkeypatch, RunFakeAPI(step_count=700))


async def test_a_control_set_over_the_limit_keeps_its_count(
    run_api: RunFakeAPI,
) -> None:
    result = await run_positive_negative_controls(
        _config(), positive_controls=OVER_THE_LIMIT
    )

    assert result.positive is not None
    assert result.positive.controls_count == 501
    assert result.positive.intersection_count == 700
    assert result.positive.intersection_ids is None
    assert result.positive.intersection_ids_sample == []
    assert result.positive.missing_ids_sample == []
    assert result.positive.recall == pytest.approx(700 / 501)


async def test_the_run_reads_no_answer_page_over_the_limit(
    run_api: RunFakeAPI,
) -> None:
    """Above the limit the identifiers are never fetched, so None is not an empty read."""
    await run_positive_negative_controls(_config(), positive_controls=OVER_THE_LIMIT)

    assert run_api.answer_calls == []


async def test_a_control_set_at_the_limit_still_reads_its_identifiers(
    run_api: RunFakeAPI,
) -> None:
    result = await run_positive_negative_controls(
        _config(), positive_controls=OVER_THE_LIMIT[:500]
    )

    assert run_api.answer_calls != []
    assert result.positive is not None
    assert result.positive.intersection_ids == ["PF3D7_0100100"]

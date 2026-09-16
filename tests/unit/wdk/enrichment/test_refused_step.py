"""An enrichment on a step the site will not run reports words, and logs the refusal."""

from __future__ import annotations

import structlog.testing
from tests._support.enrichment_wdk import FakeStrategyAPI, wdk
from tests._support.wdk_refusals import STALE_DATASET_REFUSAL, STALE_VALUE

from veupathdb_mcp.wdk.enrichment.service import EnrichmentService

__all__ = ["wdk"]

_READABLE = (
    "This strategy cannot run. The second input of the step you ran sets "
    f"'profileset_generic' to '{STALE_VALUE}', which the site no longer "
    "offers. Open that step and choose a value the site offers now."
)


async def test_a_refused_step_reports_words_and_logs_the_refusal(
    wdk: FakeStrategyAPI,
) -> None:
    wdk.refusals["go-enrichment"] = STALE_DATASET_REFUSAL

    with structlog.testing.capture_logs() as events:
        results, errors = await EnrichmentService().run_batch(
            site_id="plasmodb",
            analysis_types=["go_function"],
            search_name="GeneByLocusTag",
            parameters={},
        )

    assert errors == [f"go_function: {_READABLE}"]
    assert results[0].error == _READABLE
    logged = [
        event["error"] for event in events if event["event"] == "Enrichment failed"
    ]
    assert len(logged) == 1
    assert logged[0].endswith(STALE_DATASET_REFUSAL)

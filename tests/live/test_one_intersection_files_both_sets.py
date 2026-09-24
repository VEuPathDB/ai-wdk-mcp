"""One intersection against one dataset files both control sets as the site answers."""

from __future__ import annotations

import pytest
from veupathdb.domain.parameters import MultiPickValue, SinglePickValue
from veupathdb.wdk import (
    NewStepSpec,
    StrategyAPI,
    WDKSearchConfig,
    WDKStepTree,
    encode_params,
    get_strategy_api,
    is_internal_wdk_strategy_name,
    strip_internal_wdk_strategy_name,
)

from veupathdb_mcp.controls import (
    CONTROLS_PARAM,
    CONTROLS_SEARCH,
    ControlTestResult,
    IntersectionConfig,
    delete_temp_strategy,
    run_positive_negative_controls,
    run_step_control_tests,
)

pytestmark = pytest.mark.live_wdk

SITE = "plasmodb"
STRATEGY_NAME = "live lane one intersection"
SIGNAL_PEPTIDE = "GenesWithSignalPeptide"
PARAMETERS = {
    "organism": MultiPickValue(values=["Plasmodium falciparum 3D7"]),
    "signalp_version": SinglePickValue(value="SignalP-6.0"),
}
RECOVERED = ["PF3D7_0100600", "PF3D7_0100900", "PF3D7_0101000"]
MISSED = ["PF3D7_0100800", "PF3D7_0102700"]
ADMITTED = ["PF3D7_0508800"]
EXCLUDED = ["PF3D7_0111300", "PF3D7_0215800"]


def _config() -> IntersectionConfig:
    return IntersectionConfig(
        site_id=SITE,
        record_type="transcript",
        target_search_name=SIGNAL_PEPTIDE,
        target_parameters=dict(PARAMETERS),
        controls_search_name=CONTROLS_SEARCH,
        controls_param_name=CONTROLS_PARAM,
        internal_strategy_name=STRATEGY_NAME,
    )


def _filed(
    result: ControlTestResult,
) -> tuple[list[str], list[str], list[str], list[str]]:
    assert result.positive is not None
    assert result.negative is not None
    return (
        result.positive.recovered_ids,
        result.positive.missed_ids,
        result.negative.admitted_ids,
        result.negative.excluded_ids,
    )


async def _whole_answer(api: StrategyAPI) -> ControlTestResult:
    """Every record of the search, read page by page from a strategy it sits in."""
    step = await api.create_step(
        NewStepSpec(
            search_name=SIGNAL_PEPTIDE,
            search_config=WDKSearchConfig(parameters=encode_params(PARAMETERS)),
            custom_name="whole answer",
        ),
        record_type="transcript",
    )
    created = await api.create_strategy(
        step_tree=WDKStepTree(step_id=step.id),
        name=STRATEGY_NAME,
        is_internal=True,
    )
    try:
        return await run_step_control_tests(
            SITE, step.id, RECOVERED + MISSED, ADMITTED + EXCLUDED
        )
    finally:
        await delete_temp_strategy(api, created.id)


async def _leftovers(api: StrategyAPI) -> list[int]:
    return [
        summary.strategy_id
        for summary in await api.list_strategies()
        if is_internal_wdk_strategy_name(summary.name)
        and strip_internal_wdk_strategy_name(summary.name) == STRATEGY_NAME
    ]


async def test_both_sets_file_as_the_whole_answer_and_as_two_runs(
    wdk_identity: str,
) -> None:
    del wdk_identity
    api = get_strategy_api(SITE)

    both = await run_positive_negative_controls(
        _config(),
        positive_controls=RECOVERED + MISSED,
        negative_controls=ADMITTED + EXCLUDED,
    )
    positives_alone = await run_positive_negative_controls(
        _config(), positive_controls=RECOVERED + MISSED
    )
    negatives_alone = await run_positive_negative_controls(
        _config(), negative_controls=ADMITTED + EXCLUDED
    )
    whole = await _whole_answer(api)

    assert _filed(both) == (RECOVERED, MISSED, ADMITTED, EXCLUDED)
    assert positives_alone.positive == both.positive
    assert negatives_alone.negative == both.negative
    assert _filed(whole) == _filed(both)
    assert both.target.estimated_size == whole.target.estimated_size
    assert await _leftovers(api) == []

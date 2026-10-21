"""A control test files every control id, and reads each count from its list."""

import pytest
from pydantic import ValidationError
from tests._support.control_run_wdk import (
    RunFakeAPI,
    StepRunFakeAPI,
    gene_records,
    patch_control_run,
    patch_step_run,
)

from veupathdb_mcp.controls import (
    IntersectionConfig,
    NegativeControls,
    PositiveControls,
    run_positive_negative_controls,
    run_step_control_tests,
)
from veupathdb_mcp.tool_payloads import ControlOutcome

POSITIVES = [f"PF3D7_01{i:05d}" for i in range(25)]
NEGATIVES = [f"PF3D7_02{i:05d}" for i in range(30)]
OTHER_GENES = [f"PF3D7_03{i:05d}" for i in range(100)]
STEP_GENES = POSITIVES[:23] + OTHER_GENES + NEGATIVES[:4]


@pytest.fixture
def step_api(monkeypatch: pytest.MonkeyPatch) -> StepRunFakeAPI:
    return patch_step_run(monkeypatch, StepRunFakeAPI(gene_records(*STEP_GENES)))


async def _run_on_step() -> ControlOutcome:
    result = await run_step_control_tests(
        site_id="plasmodb",
        wdk_step_id=4242,
        positive_controls=POSITIVES,
        negative_controls=NEGATIVES,
    )
    return ControlOutcome.model_validate(result)


async def test_every_positive_is_filed_as_recovered_or_missed(
    step_api: StepRunFakeAPI,
) -> None:
    result = await run_step_control_tests(
        site_id="plasmodb", wdk_step_id=4242, positive_controls=POSITIVES
    )

    assert result.positive is not None
    assert result.positive.recovered_ids == POSITIVES[:23]
    assert result.positive.missed_ids == POSITIVES[23:]


async def test_every_negative_is_filed_as_admitted_or_excluded(
    step_api: StepRunFakeAPI,
) -> None:
    result = await run_step_control_tests(
        site_id="plasmodb", wdk_step_id=4242, negative_controls=NEGATIVES
    )

    assert result.negative is not None
    assert result.negative.admitted_ids == NEGATIVES[:4]
    assert result.negative.excluded_ids == NEGATIVES[4:]


async def test_the_counts_and_the_rates_are_read_from_the_lists(
    step_api: StepRunFakeAPI,
) -> None:
    outcome = await _run_on_step()

    assert outcome.positive_controls_count == 25
    assert outcome.positive_intersection == 23
    assert outcome.positive_recall == pytest.approx(23 / 25)
    assert outcome.negative_controls_count == 30
    assert outcome.negative_intersection == 4
    assert outcome.negative_false_positive_rate == pytest.approx(4 / 30)


async def test_the_dict_form_carries_every_id(step_api: StepRunFakeAPI) -> None:
    result = await run_step_control_tests(
        site_id="plasmodb",
        wdk_step_id=4242,
        positive_controls=POSITIVES,
        negative_controls=NEGATIVES,
    )

    wire = result.model_dump(by_alias=True, mode="json")

    assert wire["positive"] == {
        "recoveredIds": POSITIVES[:23],
        "missedIds": POSITIVES[23:],
        "controlsCount": 25,
        "intersectionCount": 23,
        "recall": pytest.approx(23 / 25),
    }
    assert wire["negative"] == {
        "admittedIds": NEGATIVES[:4],
        "excludedIds": NEGATIVES[4:],
        "controlsCount": 30,
        "intersectionCount": 4,
        "falsePositiveRate": pytest.approx(4 / 30),
    }


async def test_the_flat_dict_form_carries_every_id(step_api: StepRunFakeAPI) -> None:
    wire = (await _run_on_step()).model_dump(by_alias=True, mode="json")

    assert wire["positiveRecoveredIds"] == POSITIVES[:23]
    assert wire["positiveMissedIds"] == POSITIVES[23:]
    assert wire["negativeAdmittedIds"] == NEGATIVES[:4]
    assert wire["negativeExcludedIds"] == NEGATIVES[4:]
    assert (wire["positiveIntersection"], wire["positiveControlsCount"]) == (23, 25)
    assert (wire["negativeIntersection"], wire["negativeControlsCount"]) == (4, 30)


async def test_the_flat_dict_form_reads_back_as_the_same_outcome(
    step_api: StepRunFakeAPI,
) -> None:
    outcome = await _run_on_step()

    assert ControlOutcome.model_validate(outcome.model_dump(by_alias=True)) == outcome


async def test_a_step_is_read_only_through_the_controls(
    step_api: StepRunFakeAPI,
) -> None:
    outcome = await _run_on_step()

    assert step_api.datasets == [POSITIVES + NEGATIVES]
    assert step_api.answer_calls == [step_api.trees[0].step_id]
    assert outcome.negative_admitted_ids == NEGATIVES[:4]
    assert outcome.positive_missed_ids == POSITIVES[23:]


def test_a_count_is_not_taken_apart_from_its_list() -> None:
    controls = PositiveControls.model_validate(
        {"recoveredIds": ["PF3D7_0100100"], "missedIds": [], "controlsCount": 9}
    )

    assert controls.controls_count == 1


def test_an_id_filed_on_both_lists_is_refused() -> None:
    with pytest.raises(ValidationError, match="PF3D7_0100100"):
        NegativeControls(admitted_ids=["PF3D7_0100100"], excluded_ids=["PF3D7_0100100"])


def test_a_control_set_without_an_id_is_refused() -> None:
    with pytest.raises(ValidationError, match="at least one"):
        PositiveControls(recovered_ids=[], missed_ids=[])


def _search_config() -> IntersectionConfig:
    return IntersectionConfig(
        site_id="plasmodb",
        record_type="transcript",
        target_search_name="GenesByMolecularWeight",
        target_parameters={},
        controls_search_name="GeneByLocusTag",
        controls_param_name="ds_gene_ids",
    )


async def test_a_search_test_files_every_control(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_control_run(monkeypatch, RunFakeAPI(answer_ids=tuple(STEP_GENES)))

    result = await run_positive_negative_controls(
        _search_config(), positive_controls=POSITIVES, negative_controls=NEGATIVES
    )

    assert result.positive is not None
    assert result.positive.recovered_ids == POSITIVES[:23]
    assert result.positive.missed_ids == POSITIVES[23:]
    assert result.negative is not None
    assert result.negative.admitted_ids == NEGATIVES[:4]
    assert result.negative.excluded_ids == NEGATIVES[4:]


async def test_a_search_test_of_any_size_reads_every_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    many = [f"PF3D7_{i:07d}" for i in range(1, 1202)]
    api = patch_control_run(monkeypatch, RunFakeAPI(answer_ids=(many[0],)))

    result = await run_positive_negative_controls(
        _search_config(), positive_controls=many
    )

    assert api.answer_calls != []
    assert result.positive is not None
    assert result.positive.recovered_ids == [many[0]]
    assert result.positive.missed_ids == many[1:]
    assert result.positive.controls_count == 1201

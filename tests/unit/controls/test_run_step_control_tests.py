"""A built step is tested by intersecting a copy of it with the controls on the site."""

import pytest
from tests._support.control_run_wdk import (
    COPY_OFFSET,
    TESTED_STEP,
    StepRunFakeAPI,
    gene_records,
    patch_step_run,
)
from veupathdb.domain.strategy import CombineOp
from veupathdb.errors import ValidationError
from veupathdb.testing.wdk_fixtures import load_recorded
from veupathdb.wdk import WDKAnswer, WDKStepTree

from veupathdb_mcp.controls import (
    ControlsSearch,
    ControlTestResult,
    run_step_control_tests,
)
from veupathdb_mcp.tool_payloads import ControlOutcome
from veupathdb_mcp.wdk import TRANSCRIPTS_PER_GENE
from veupathdb_mcp.wdk.step_report_filters import representative_transcript_only

STEP_GENES = ("PF3D7_0100100", "PF3D7_0100200", "PF3D7_0100300")
COPY = TESTED_STEP + COPY_OFFSET


@pytest.fixture
def site(monkeypatch: pytest.MonkeyPatch) -> StepRunFakeAPI:
    return patch_step_run(monkeypatch, StepRunFakeAPI(gene_records(*STEP_GENES)))


async def test_positive_controls_report_recall(site: StepRunFakeAPI) -> None:
    result = await run_step_control_tests(
        site_id="plasmodb",
        wdk_step_id=TESTED_STEP,
        positive_controls=["PF3D7_0100100", "PF3D7_0100200", "PF3D7_9999999"],
    )
    assert isinstance(result, ControlTestResult)
    assert result.site_id == "plasmodb"
    assert result.target.step_id == TESTED_STEP
    assert result.target.estimated_size == 3
    assert result.positive is not None
    assert result.positive.recall == pytest.approx(2 / 3)
    assert result.positive.recovered_ids == ["PF3D7_0100100", "PF3D7_0100200"]
    assert result.positive.missed_ids == ["PF3D7_9999999"]
    assert result.negative is None


async def test_negative_controls_report_false_positive_rate(
    site: StepRunFakeAPI,
) -> None:
    result = await run_step_control_tests(
        site_id="plasmodb",
        wdk_step_id=TESTED_STEP,
        negative_controls=["PF3D7_0100300", "PF3D7_8888888"],
    )
    assert result.negative is not None
    assert result.negative.false_positive_rate == pytest.approx(0.5)
    assert result.negative.admitted_ids == ["PF3D7_0100300"]
    assert result.negative.excluded_ids == ["PF3D7_8888888"]
    assert result.positive is None


async def test_the_steps_own_records_are_never_read(site: StepRunFakeAPI) -> None:
    await run_step_control_tests(
        site_id="plasmodb",
        wdk_step_id=TESTED_STEP,
        positive_controls=["PF3D7_0100100"],
        negative_controls=["PF3D7_0100300"],
    )

    combine = site.combines[0]
    assert (combine.primary_step_id, combine.boolean_operator) == (
        COPY,
        CombineOp.INTERSECT,
    )
    assert site.answer_calls == [site.trees[0].step_id]
    assert TESTED_STEP not in site.answer_calls + site.count_calls
    assert site.datasets == [["PF3D7_0100100", "PF3D7_0100300"]]
    assert site.deleted == [8000]


async def test_a_step_inside_a_larger_strategy_is_copied_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tree = WDKStepTree(
        step_id=4300,
        primary_input=WDKStepTree(step_id=TESTED_STEP),
        secondary_input=WDKStepTree(step_id=4250),
    )
    site = patch_step_run(
        monkeypatch, StepRunFakeAPI(gene_records(*STEP_GENES), strategy_tree=tree)
    )

    await run_step_control_tests("plasmodb", TESTED_STEP, ["PF3D7_0100100"])

    assert site.combines[0].primary_step_id == COPY
    assert site.deleted_steps == [4250 + COPY_OFFSET, 4300 + COPY_OFFSET]
    assert site.most_deletes_in_flight == 1
    assert site.trees[0].primary_input == WDKStepTree(step_id=COPY)
    assert site.holds() == ([], [])


async def test_no_controls_reads_only_the_count(site: StepRunFakeAPI) -> None:
    result = await run_step_control_tests(site_id="plasmodb", wdk_step_id=1)

    assert (result.positive, result.negative) == (None, None)
    assert (result.target.step_id, result.target.estimated_size) == (1, 3)
    assert site.calls == ["get_step_count"]


async def test_a_transcript_intersection_is_read_one_row_per_gene(
    site: StepRunFakeAPI,
) -> None:
    await run_step_control_tests("plasmodb", TESTED_STEP, ["PF3D7_0100100"])

    assert site.answer_view_filters == [[representative_transcript_only()]]


async def test_a_step_of_another_record_type_is_refused_before_a_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = patch_step_run(
        monkeypatch,
        StepRunFakeAPI(gene_records(*STEP_GENES), record_class_name="sequence"),
    )

    with pytest.raises(ValidationError, match=r"sequence.*transcript"):
        await run_step_control_tests("orthomcl", TESTED_STEP, ["PF3D7_0100100"])
    assert site.calls == ["find_step"]


async def test_a_host_names_the_id_search_of_its_record_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proteins = ("PF3D7_1133400.1-p1", "PF3D7_0100100.1-p1")
    site = patch_step_run(
        monkeypatch,
        StepRunFakeAPI(gene_records(*proteins), record_class_name="sequence"),
    )

    result = await run_step_control_tests(
        "orthomcl",
        TESTED_STEP,
        ["PF3D7_1133400.1-p1", "PF3D7_9999999.1-p1"],
        controls=ControlsSearch(
            search_name="ByIdList", param_name="source_ids", record_type="sequence"
        ),
    )

    assert [spec.search_name for spec in site.steps] == ["ByIdList"]
    assert result.positive is not None
    assert result.positive.recovered_ids == ["PF3D7_1133400.1-p1"]
    assert site.answer_view_filters == [None]


async def test_a_step_outside_a_strategy_is_refused_before_a_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = patch_step_run(
        monkeypatch, StepRunFakeAPI(gene_records(*STEP_GENES), strategy_id=None)
    )

    with pytest.raises(ValidationError, match="no strategy"):
        await run_step_control_tests("plasmodb", TESTED_STEP, ["PF3D7_0100100"])
    assert site.calls == ["find_step"]


async def test_a_recorded_report_files_the_genes_it_holds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorded = WDKAnswer.model_validate(
        load_recorded("answer_report_by_molecular_weight").body
    ).records
    held = [record.display_name for record in recorded[:2]]
    patch_step_run(monkeypatch, StepRunFakeAPI(recorded))

    result = await run_step_control_tests(
        "plasmodb", TESTED_STEP, [*held, "PF3D7_9999999"]
    )

    assert result.positive is not None
    assert result.positive.recovered_ids == sorted(held)
    assert result.positive.missed_ids == ["PF3D7_9999999"]


async def test_the_payload_layer_flattens_the_result(site: StepRunFakeAPI) -> None:
    result = await run_step_control_tests(
        site_id="plasmodb",
        wdk_step_id=TESTED_STEP,
        positive_controls=["PF3D7_0100100", "PF3D7_9999999"],
        negative_controls=["PF3D7_0100300"],
    )

    outcome = ControlOutcome.model_validate(result)

    assert outcome.step_id == TESTED_STEP
    assert outcome.estimated_size == 3
    assert outcome.positive_recovered_ids == ["PF3D7_0100100"]
    assert outcome.positive_missed_ids == ["PF3D7_9999999"]
    assert outcome.negative_admitted_ids == ["PF3D7_0100300"]
    assert outcome.negative_excluded_ids == []


async def test_the_intersection_asks_for_a_fixed_number_of_records_per_control(
    site: StepRunFakeAPI,
) -> None:
    await run_step_control_tests(
        "plasmodb", TESTED_STEP, ["PF3D7_0100100"], ["PF3D7_0100300"]
    )

    assert site.answer_paginations == [
        {"offset": 0, "numRecords": 2 * TRANSCRIPTS_PER_GENE + 1}
    ]


async def test_an_intersection_past_the_bound_is_refused_naming_the_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    many = gene_records(*["PF3D7_0100100"] * (TRANSCRIPTS_PER_GENE + 1))
    site = patch_step_run(monkeypatch, StepRunFakeAPI(many))

    with pytest.raises(
        ValidationError,
        match=rf"GeneByLocusTag answered more than {TRANSCRIPTS_PER_GENE} records "
        "for 1 control ids",
    ):
        await run_step_control_tests("plasmodb", TESTED_STEP, ["PF3D7_0100100"])
    assert site.holds() == ([], [])

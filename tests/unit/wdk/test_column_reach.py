from __future__ import annotations

from tests._support.column_site import GROUP_STEP, STEP, ColumnSite, column_site
from tests._support.orthomcl_catalog import (
    build_attributes,
    genes_by_orthologs,
    orthomcl_group,
    orthomcl_record_types,
    orthomcl_sequence,
)
from veupathdb.wdk import WDKRecordType

from veupathdb_mcp.catalog.search_offer import (
    is_boolean_search,
    transforms_one_step_of,
)
from veupathdb_mcp.wdk import (
    StepColumn,
    TransformColumns,
    list_step_columns,
    transforms_from,
)

__all__ = ["column_site"]

FROM_GROUPS = TransformColumns(
    search_name="FromGroups",
    display_name="Transform Groups to Proteins",
    record_type="sequence",
    columns=(),
)


def test_a_recorded_group_step_reaches_the_proteins_and_no_counted_column() -> None:
    assert transforms_from(orthomcl_record_types(), "group") == (FROM_GROUPS,)


def test_a_reached_record_type_names_its_recorded_by_value_columns() -> None:
    proteins_with_build_columns = orthomcl_sequence().model_copy(
        update={"attributes": build_attributes()}
    )

    reached = transforms_from([orthomcl_group(), proteins_with_build_columns], "group")

    assert reached == (
        TransformColumns(
            search_name="FromGroups",
            display_name="Transform Groups to Proteins",
            record_type="sequence",
            columns=(
                StepColumn(
                    name="primary_key",
                    display_name="VEuPathDB Build Number",
                    data_type="STRING",
                    countable=True,
                ),
                StepColumn(
                    name="build_number",
                    display_name="build_number",
                    data_type="STRING",
                    countable=True,
                ),
            ),
        ),
    )


def test_a_search_back_into_the_same_record_type_reaches_nothing() -> None:
    orthologs = genes_by_orthologs()
    transcripts = WDKRecordType(url_segment="transcript", searches=[orthologs])

    assert transforms_one_step_of(orthologs, "transcript")
    assert transforms_from([transcripts], "transcript") == ()


def test_a_combine_of_two_steps_is_no_transform() -> None:
    combines = [
        s
        for r in orthomcl_record_types()
        for s in r.searches or []
        if s.allowed_secondary_input_record_class_names
    ]
    reached = transforms_from(orthomcl_record_types(), "sequence")

    assert [(s.url_segment, is_boolean_search(s)) for s in combines] == [
        ("boolean_question_GroupRecordClasses_GroupRecordClass", True),
        ("boolean_question_SequenceRecordClasses_SequenceRecordClass", True),
    ]
    assert [transforms_one_step_of(s, "group") for s in combines] == [False, False]
    assert [t.search_name for t in reached] == ["GroupsFromSequences"]


async def test_a_transcript_step_reaches_no_other_record_type(
    column_site: ColumnSite,
) -> None:
    listed = await list_step_columns("plasmodb", STEP)

    assert (listed.record_type, listed.transforms) == ("transcript", ())
    assert column_site.record_types_read == ["plasmodb"]


async def test_a_group_step_lists_the_transform_its_records_take(
    column_site: ColumnSite,
) -> None:
    listed = await list_step_columns("orthomcl", GROUP_STEP)

    assert (listed.record_type, listed.search_name) == (
        "group",
        "GroupsBySequenceCount",
    )
    assert listed.transforms == (FROM_GROUPS,)
    assert column_site.record_types_read == ["orthomcl"]

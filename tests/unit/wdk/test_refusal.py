"""A step the site will not run says so in words a researcher reads."""

from __future__ import annotations

import pytest
from tests._support.wdk_refusals import (
    FIRST_INPUT_REFUSAL,
    MARKUP_VALUE_REFUSAL,
    NOT_A_VALIDATION_REFUSAL,
    OWN_VALUE_REFUSAL,
    STALE_DATASET_REFUSAL,
    STALE_VALUE,
    TRANSFORM_INPUT_REFUSAL,
    UNREADABLE_REFUSAL,
)

from veupathdb_mcp.wdk.refusal import describe_step_refusal

_INTERNALS = (
    "1202189953",
    "440118373",
    "440118363",
    "keyedErrors",
    "validationLevel",
    "validationStatus",
    "HTTP",
    "{",
    "}",
    "\\",
)


def test_a_nested_stale_value_names_the_input_the_parameter_and_the_value() -> None:
    read = describe_step_refusal(STALE_DATASET_REFUSAL)

    assert read == (
        "This strategy cannot run. The second input of the step you ran sets "
        f"'profileset_generic' to '{STALE_VALUE}', which the site no longer "
        "offers. Open that step and choose a value the site offers now."
    )


@pytest.mark.parametrize("token", _INTERNALS)
def test_the_sentence_carries_no_internal_text(token: str) -> None:
    read = describe_step_refusal(STALE_DATASET_REFUSAL)

    assert read is not None
    assert token not in read


def test_a_refusal_about_the_step_itself_names_that_step() -> None:
    read = describe_step_refusal(OWN_VALUE_REFUSAL)

    assert read == (
        "This strategy cannot run. The step you ran sets 'organism' to "
        "'Plasmodium berghei ANKA', which the site no longer offers. Open that "
        "step and choose a value the site offers now."
    )


def test_a_left_operand_names_the_first_input() -> None:
    read = describe_step_refusal(FIRST_INPUT_REFUSAL)

    assert read == (
        "This strategy cannot run. The first input of the step you ran sets "
        "'organism' to 'Plasmodium berghei ANKA', which the site no longer "
        "offers. Open that step and choose a value the site offers now."
    )


def test_a_bundle_whose_message_is_unread_gives_one_short_sentence() -> None:
    read = describe_step_refusal(UNREADABLE_REFUSAL)

    assert read == (
        "This strategy cannot run. The site refused one of its steps and did "
        "not name the value at fault. Open the strategy and check its steps."
    )
    assert "samples_fold_change_generic" not in read


def test_a_failure_that_carries_no_bundle_is_left_to_its_caller() -> None:
    assert describe_step_refusal(NOT_A_VALIDATION_REFUSAL) is None
    assert describe_step_refusal("the analysis plugin refused") is None


def test_a_value_that_is_markup_is_not_quoted_back() -> None:
    read = describe_step_refusal(MARKUP_VALUE_REFUSAL)

    assert read == (
        "This strategy cannot run. The site refused one of its steps and did "
        "not name the value at fault. Open the strategy and check its steps."
    )


def test_an_answer_parameter_that_is_no_operand_names_an_earlier_step() -> None:
    read = describe_step_refusal(TRANSFORM_INPUT_REFUSAL)

    assert read == (
        "This strategy cannot run. An earlier step in this strategy sets "
        "'organism' to 'Plasmodium berghei ANKA', which the site no longer "
        "offers. Open that step and choose a value the site offers now."
    )

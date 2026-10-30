"""A run refuses control counts no candidate can tell apart, before any request."""

import math

import pytest
from pydantic import ValidationError

from veupathdb_mcp.controls import NegativeControls, PositiveControls
from veupathdb_mcp.separation import (
    INFORMATIVE_P_VALUE,
    TooFewControls,
    too_few_controls,
)
from veupathdb_mcp.separation.models import informs


def _ids(prefix: str, count: int) -> list[str]:
    return [f"PF3D7_{prefix}{i:05d}" for i in range(count)]


def _short(positives: int, negatives: int) -> TooFewControls | None:
    return too_few_controls(_ids("01", positives), _ids("02", negatives))


def _some_read_recovers(positives: int, negatives: int) -> bool:
    tested_positive, tested_negative = _ids("01", positives), _ids("02", negatives)
    return any(
        informs(
            PositiveControls.filed(tested_positive, set(tested_positive[:recovered])),
            NegativeControls.filed(tested_negative, set(tested_negative[:admitted])),
        )
        == "recovering"
        for recovered in range(positives + 1)
        for admitted in range(negatives + 1)
    )


def test_four_positives_and_two_negatives_are_too_few() -> None:
    short = _short(4, 2)

    assert short is not None
    assert (short.positives, short.negatives) == (4, 2)
    assert short.best_p_value == pytest.approx(1 / 15)
    assert (short.more_negatives, short.more_positives) == (1, 1)


def test_four_positives_and_three_negatives_can_separate() -> None:
    assert _short(4, 3) is None


def test_a_best_tail_of_exactly_the_threshold_is_too_few() -> None:
    short = _short(3, 3)

    assert short is not None
    assert short.best_p_value == pytest.approx(1 / 20)
    assert (short.more_negatives, short.more_positives) == (1, 1)


@pytest.mark.parametrize(
    ("positives", "negatives", "too_few"),
    [(5, 2, False), (3, 3, True), (1, 20, False), (1, 19, True), (19, 1, True)],
)
def test_the_boundary_is_strict_on_each_side(
    positives: int, negatives: int, too_few: bool
) -> None:
    assert (_short(positives, negatives) is not None) == too_few


def test_every_positive_and_no_negative_of_three_each_informs_nothing() -> None:
    tested_positive, tested_negative = _ids("01", 3), _ids("02", 3)

    assert (
        informs(
            PositiveControls.filed(tested_positive, set(tested_positive)),
            NegativeControls.filed(tested_negative, set()),
        )
        == "neither"
    )


@pytest.mark.parametrize(
    ("positives", "negatives", "more_negatives", "more_positives"),
    [(1, 1, 19, 19), (2, 2, 3, 3), (10, 1, 1, 10), (1, 5, 15, 1), (2, 4, 1, 1)],
)
def test_the_counts_to_add_are_the_smallest_that_beat_chance(
    positives: int, negatives: int, more_negatives: int, more_positives: int
) -> None:
    short = _short(positives, negatives)

    assert short is not None
    assert (short.more_negatives, short.more_positives) == (
        more_negatives,
        more_positives,
    )
    assert _short(positives, negatives + more_negatives) is None
    assert _short(positives, negatives + more_negatives - 1) is not None
    assert _short(positives + more_positives, negatives) is None
    assert _short(positives + more_positives - 1, negatives) is not None


@pytest.mark.parametrize("positives", range(1, 9))
@pytest.mark.parametrize("negatives", range(1, 9))
def test_too_few_means_no_read_of_the_controls_recovers(
    positives: int, negatives: int
) -> None:
    short = _short(positives, negatives)

    assert (short is None) == _some_read_recovers(positives, negatives)
    if short is not None:
        assert short.best_p_value == pytest.approx(
            1 / math.comb(positives + negatives, positives)
        )


def test_a_repeated_or_blank_id_counts_once() -> None:
    short = too_few_controls(["A", "A ", " ", "B", "C", "D"], ["X", "Y", "Y"])

    assert short is not None
    assert (short.positives, short.negatives) == (4, 2)


def test_an_empty_list_is_refused() -> None:
    with pytest.raises(ValueError, match="no negative control"):
        too_few_controls(["A"], [" "])


def test_counts_that_can_separate_are_not_too_few() -> None:
    with pytest.raises(ValidationError, match="can return the positives"):
        TooFewControls(positives=4, negatives=3)


def test_the_sentence_states_the_counts_and_what_to_add() -> None:
    short = _short(4, 2)

    assert short is not None
    assert short.sentence == (
        "With 4 positive and 2 negative controls, the best any search can reach "
        "is p = 0.067, and a result needs p under 0.05. Add 1 more negative "
        "control or 1 more positive control."
    )


def test_the_wire_carries_the_computed_counts() -> None:
    short = _short(2, 2)

    assert short is not None
    wire = short.model_dump(by_alias=True, mode="json")
    assert {k: wire[k] for k in ("moreNegatives", "morePositives", "threshold")} == {
        "moreNegatives": 3,
        "morePositives": 3,
        "threshold": INFORMATIVE_P_VALUE,
    }
    assert wire["chargedRequests"] == 0

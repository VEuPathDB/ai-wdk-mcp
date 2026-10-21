import math

import pytest
from pydantic import ValidationError

from veupathdb_mcp.audit.rates import WILSON_Z, RateBounds, rate_with_bounds

Z = 1.959963984540054


def hand_wilson(confirmed: int, checked: int) -> tuple[float, float]:
    p = confirmed / checked
    scale = 1 + Z * Z / checked
    centre = p + Z * Z / (2 * checked)
    half = Z * math.sqrt(p * (1 - p) / checked + Z * Z / (4 * checked * checked))
    return (centre - half) / scale, (centre + half) / scale


def test_the_interval_is_the_wilson_95_percent_interval() -> None:
    assert WILSON_Z == Z


def test_a_rate_states_its_interval_floor_and_ceiling() -> None:
    bounds = rate_with_bounds(15, 36, 61)

    low, high = hand_wilson(15, 36)
    assert bounds.rate == pytest.approx(15 / 36)
    assert bounds.low == pytest.approx(low, abs=1e-12)
    assert bounds.high == pytest.approx(high, abs=1e-12)
    assert round(bounds.low, 4) == 0.2714
    assert round(bounds.high, 4) == 0.578
    assert bounds.low < bounds.rate < bounds.high
    assert bounds.floor == pytest.approx(15 / 97)
    assert bounds.ceiling == pytest.approx(76 / 97)
    assert (bounds.confirmed, bounds.checked, bounds.unresolved) == (15, 36, 61)


def test_no_confirmed_call_has_a_lower_bound_of_zero() -> None:
    bounds = rate_with_bounds(0, 10, 0)

    assert bounds.low == 0
    assert bounds.rate == 0
    assert bounds.high == pytest.approx(hand_wilson(0, 10)[1], abs=1e-12)
    assert round(bounds.high, 4) == 0.2775
    assert (bounds.floor, bounds.ceiling) == (0, 0)


def test_every_call_confirmed_has_an_upper_bound_of_one() -> None:
    bounds = rate_with_bounds(10, 10, 0)

    assert bounds.high == 1
    assert bounds.low == pytest.approx(hand_wilson(10, 10)[0], abs=1e-12)
    assert (bounds.floor, bounds.ceiling) == (1, 1)


@pytest.mark.parametrize("checked", [15, 16, 28, 200])
def test_every_call_confirmed_has_an_upper_bound_of_exactly_one(checked: int) -> None:
    assert rate_with_bounds(checked, checked, 0).high == 1


def test_the_interval_stays_in_the_unit_range_and_holds_the_rate() -> None:
    outside = [
        (confirmed, checked)
        for checked in range(1, 20001)
        for confirmed in {0, checked, checked // 2}
        if not (
            0
            <= (bounds := rate_with_bounds(confirmed, checked, 0)).low
            <= bounds.rate
            <= bounds.high
            <= 1
        )
    ]

    assert outside == []


def test_the_interval_is_symmetric() -> None:
    bounds, mirror = rate_with_bounds(7, 30, 0), rate_with_bounds(23, 30, 0)

    assert bounds.high == 1 - mirror.low
    assert bounds.low == pytest.approx(1 - mirror.high, abs=1e-15)


def test_no_checked_call_gives_rate_zero_and_the_whole_interval() -> None:
    bounds = rate_with_bounds(0, 0, 4)

    assert (bounds.rate, bounds.low, bounds.high) == (0, 0, 1)
    assert (bounds.floor, bounds.ceiling) == (0, 1)


def test_no_call_at_all_gives_the_whole_range() -> None:
    bounds = rate_with_bounds(0, 0, 0)

    assert (bounds.rate, bounds.low, bounds.high) == (0, 0, 1)
    assert (bounds.floor, bounds.ceiling) == (0, 1)


def test_the_bounds_serve_in_camel_case() -> None:
    served = rate_with_bounds(1, 2, 1).model_dump(by_alias=True)

    assert sorted(served) == [
        "ceiling",
        "checked",
        "confirmed",
        "floor",
        "high",
        "low",
        "rate",
        "unresolved",
    ]
    assert served["floor"] == pytest.approx(1 / 3)
    assert served["ceiling"] == pytest.approx(2 / 3)


@pytest.mark.parametrize(
    ("confirmed", "checked", "unresolved"),
    [(3, 2, 0), (-1, 2, 0), (1, 2, -1)],
)
def test_counts_that_cannot_hold_are_refused(
    confirmed: int, checked: int, unresolved: int
) -> None:
    with pytest.raises(ValidationError):
        rate_with_bounds(confirmed, checked, unresolved)


def test_bounds_are_derived_and_not_given() -> None:
    with pytest.raises(ValidationError):
        RateBounds.model_validate(
            {"confirmed": 1, "checked": 2, "unresolved": 0, "rate": 0.9}
        )

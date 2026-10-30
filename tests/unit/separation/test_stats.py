"""The hypergeometric upper tail, in log space and exact, against the sum of binomials."""

import math
from fractions import Fraction

import pytest

from veupathdb_mcp.separation import hypergeometric_log_sf
from veupathdb_mcp.separation.stats import hypergeometric_sf


def _exact_tail(x: int, n: int, k: int, m: int) -> float:
    upper = min(k, m)
    hits = sum(math.comb(k, i) * math.comb(n - k, m - i) for i in range(x, upper + 1))
    return hits / math.comb(n, m)


@pytest.mark.parametrize(
    ("x", "n", "k", "m"),
    [(52, 120, 80, 54), (80, 120, 80, 119), (3, 18, 10, 3), (5, 5300, 80, 400)],
)
def test_the_tail_is_the_exact_sum(x: int, n: int, k: int, m: int) -> None:
    assert math.exp(hypergeometric_log_sf(x, n, k, m)) == pytest.approx(
        _exact_tail(x, n, k, m), rel=1e-9
    )


def test_a_tail_from_the_lowest_count_is_certain() -> None:
    assert hypergeometric_log_sf(80, 135, 80, 135) == 0.0


def test_a_tail_past_the_highest_count_is_impossible() -> None:
    assert hypergeometric_log_sf(11, 18, 10, 12) == -math.inf


def test_a_draw_larger_than_the_population_is_refused() -> None:
    with pytest.raises(ValueError, match="not a hypergeometric distribution"):
        hypergeometric_log_sf(1, 10, 5, 11)


@pytest.mark.parametrize(
    ("x", "n", "k", "m"),
    [(52, 120, 80, 54), (80, 120, 80, 119), (3, 18, 10, 3), (3, 6, 3, 3)],
)
def test_the_exact_tail_is_the_sum_of_binomials(x: int, n: int, k: int, m: int) -> None:
    upper = min(k, m)
    hits = sum(math.comb(k, i) * math.comb(n - k, m - i) for i in range(x, upper + 1))

    assert hypergeometric_sf(x, n, k, m) == Fraction(hits, math.comb(n, m))


def test_the_exact_tail_of_three_in_six_is_one_twentieth() -> None:
    assert hypergeometric_sf(3, 6, 3, 3) == Fraction(1, 20)


def test_the_exact_tail_bounds() -> None:
    assert hypergeometric_sf(80, 135, 80, 135) == 1
    assert hypergeometric_sf(11, 18, 10, 12) == 0
    with pytest.raises(ValueError, match="not a hypergeometric distribution"):
        hypergeometric_sf(1, 10, 5, 11)

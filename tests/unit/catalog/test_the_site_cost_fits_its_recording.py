"""The count-time fit comes from the QA site-limit recording and predicts each of
its rows within 25%; the worst row, the 165,028-character expression, is 22.8% off."""

import inspect

import pytest

from veupathdb_mcp.catalog import site_cost as site_cost_module
from veupathdb_mcp.catalog.site_cost import SITE_LIMITS, fit, measured_rows, site_cost

TOLERANCE = 0.25


def test_the_recording_is_runtime_package_data() -> None:
    assert SITE_LIMITS.is_file()
    assert str(SITE_LIMITS).endswith(
        "veupathdb_mcp/catalog/data/orthomcl_phyletic_site_limits.json"
    )
    assert "veupathdb_mcp.testing" not in inspect.getsource(site_cost_module)


def test_the_recording_holds_every_answered_read() -> None:
    rows = measured_rows()

    assert len(rows) == 8
    assert max(characters for characters, _ in rows) == 645028


@pytest.mark.parametrize("row", measured_rows(), ids=lambda row: str(row[0]))
def test_the_fit_predicts_each_recorded_read_within_tolerance(
    row: tuple[int, float],
) -> None:
    characters, seconds = row

    predicted = site_cost().seconds(characters, 0)

    assert abs(predicted - seconds) / seconds <= TOLERANCE


def test_the_fit_is_a_fixed_cost_and_a_cost_per_character() -> None:
    cost = site_cost()

    assert (round(cost.fixed, 2), round(cost.per_character * 1e6, 1)) == (3.94, 137.8)
    assert cost == fit(measured_rows())


def test_the_budget_admits_the_characters_its_fit_allows() -> None:
    cost = site_cost()
    allowed = cost.characters_within(300, 2)

    assert cost.seconds(allowed, 2) <= 300 < cost.seconds(allowed + 10, 2)

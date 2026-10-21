import pytest
from tests._support.proteins import row

from veupathdb_mcp.audit.served import length_flank, length_span


@pytest.mark.parametrize(
    ("missing", "flank"),
    [(-40, 6000), (0, 6000), (500, 6000), (501, 6012), (2500, 30000), (4000, 30000)],
)
def test_the_flank_is_twelve_bases_per_missing_residue_within_its_bounds(
    missing: int, flank: int
) -> None:
    assert length_flank(missing) == flank


def test_the_span_is_the_parts_with_the_flank_on_each_side() -> None:
    first = row("A", "Plasmodium falciparum 3D7", 300, start=10001)
    second = row("B", "Plasmodium falciparum 3D7", 300, start=20001)

    assert length_span([first], 501) == (10001 - 6012, first.end + 6012)
    assert length_span([second, first], 0) == (10001 - 6000, second.end + 6000)

import pytest
from tests._support.audit_site import members
from tests._support.proteins import row, tight

from veupathdb_mcp.audit.lengths import Confirmable, NotChecked, call_length


def test_two_short_neighbours_that_sum_to_the_median_are_a_split() -> None:
    a = row("ME1", "Plasmodium speciesM X", 200)
    b = row("ME2", "Plasmodium speciesM X", 220)
    assert call_length([a, b], members([*tight(), a, b])).length_class == "SPLIT"


@pytest.mark.parametrize(("first", "second"), [(350, 100), (100, 150), (300, 300)])
def test_parts_too_long_or_summing_outside_the_bounds_are_typical(
    first: int, second: int
) -> None:
    a = row("ME1", "Plasmodium speciesM X", first)
    b = row("ME2", "Plasmodium speciesM X", second)
    assert call_length([a, b], members([*tight(), a, b])).length_class == "TYPICAL"


def test_a_split_in_a_small_group_cannot_judge() -> None:
    a = row("ME1", "Plasmodium speciesM X", 200)
    b = row("ME2", "Plasmodium speciesM X", 220)
    assert call_length([a, b], members([*tight(5), a, b])).length_class == "UNQUALIFIED"


def test_a_split_call_holds_its_reference_and_the_summed_ratio() -> None:
    a = row("ME1", "Plasmodium speciesM X", 200)
    b = row("ME2", "Plasmodium speciesM X", 220)

    call = call_length([a, b], members([*tight(), a, b]))

    assert type(call) is Confirmable
    assert (call.length_class, call.reference.gene, call.ratio) == ("SPLIT", "G0", 1.05)


def test_a_neighbour_outside_the_group_is_not_a_split() -> None:
    me = row("ME", "Plasmodium speciesM X", 200)
    neighbour = row("NB", "Plasmodium speciesM X", 220)

    call = call_length([me, neighbour], members([*tight(), me]))

    assert type(call) is NotChecked
    assert call.length_class == "UNQUALIFIED"


def test_a_pair_with_a_group_member_between_them_is_not_a_split() -> None:
    a = row("ME1", "Plasmodium speciesM X", 200, start=1000)
    between = row("ME2", "Plasmodium speciesM X", 150, start=3000)
    b = row("ME3", "Plasmodium speciesM X", 220, start=5000)
    same = {"sequence_id": "M_contig"}
    a, between, b = (r.model_copy(update=same) for r in (a, between, b))

    assert call_length([a, b], members([*tight(), a, between, b])).length_class == (
        "UNQUALIFIED"
    )
    assert call_length([a, b], members([*tight(), a, b])).length_class == "SPLIT"


def test_three_adjacent_members_in_one_organism_give_no_split_pair() -> None:
    a, b, c = (
        row(f"ME{i}", "Plasmodium speciesM X", n, start=1000 * i).model_copy(
            update={"sequence_id": "M_contig"}
        )
        for i, n in ((1, 200), (2, 220), (3, 200))
    )

    for pair in ([a, b], [b, c]):
        assert (
            call_length(pair, members([*tight(), a, b, c])).length_class
            == "UNQUALIFIED"
        )
        assert call_length(pair, members([*tight(), *pair])).length_class == "SPLIT"


def test_a_pair_given_in_either_order_is_the_same_split() -> None:
    a = row("ME1", "Plasmodium speciesM X", 200)
    b = row("ME2", "Plasmodium speciesM X", 220)

    forward = call_length([a, b], members([*tight(), a, b]))
    backward = call_length([b, a], members([*tight(), a, b]))

    assert (forward.length_class, backward.length_class) == ("SPLIT", "SPLIT")
    assert (forward.ratio, backward.ratio) == (1.05, 1.05)

"""Recovering candidates cover the positives; negatives go by intersection or subtraction."""

from tests._support.separation_sets import NEGATIVES, POSITIVES, measured, moves
from veupathdb.domain.strategy import CombineOp

from veupathdb_mcp.separation.assemble import assemble, leaf_ids, rank


def test_cover_takes_the_informative_full_recall_candidate_with_fewest_negatives() -> (
    None
):
    """A holds six of eight negatives, so its controls do not beat chance."""
    measured_sets = [
        measured("A", range(10), range(6), 4000),
        measured("B", range(10), [6, 7], 900),
        measured("D", range(9), [], 200),
        measured("E", range(3), [], 50),
    ]

    assembly = assemble(measured_sets, "exact", POSITIVES)

    assert [m.informs for m in measured_sets] == [
        "neither",
        "recovering",
        "recovering",
        "neither",
    ]
    assert moves(assembly.tree) == [(None, "B")]
    assert assembly.recovered == frozenset(POSITIVES)
    assert assembly.admitted == frozenset(NEGATIVES[6:])


def test_exact_mode_subtracts_the_excluding_candidate_that_holds_its_negatives() -> (
    None
):
    """C holds four negatives and no positive, B's two among them."""
    measured_sets = [
        measured("B", range(10), [6, 7], 900),
        measured("C", [], [4, 5, 6, 7], 300),
    ]

    assembly = assemble(measured_sets, "exact", POSITIVES)

    assert measured_sets[1].informs == "excluding"
    assert moves(assembly.tree) == [(None, "B"), (CombineOp.MINUS, "C")]
    assert assembly.admitted == frozenset()


def test_similar_mode_leaves_the_excluding_candidate_out() -> None:
    measured_sets = [
        measured("B", range(10), [6, 7], 900),
        measured("C", [], [4, 5, 6, 7], 300),
    ]

    assembly = assemble(measured_sets, "similar", POSITIVES)

    assert leaf_ids(assembly.tree) == ["B"]


def test_a_tie_between_intersect_and_minus_goes_to_intersect() -> None:
    measured_sets = [
        measured("K", range(10), [6, 7], 100),
        measured("T", range(10), [0, 1, 2], 900),
        measured("C", [], [4, 5, 6, 7], 10),
    ]

    assembly = assemble(measured_sets, "exact", POSITIVES)

    assert moves(assembly.tree) == [(None, "K"), (CombineOp.INTERSECT, "T")]


def test_the_intersect_that_removes_most_goes_first() -> None:
    measured_sets = [
        measured("K", range(10), [0, 1, 2, 3], 100),
        measured("M", range(10), [2, 3, 4, 5], 900),
        measured("R", range(10), [0, 1, 3, 6], 700),
    ]

    assembly = assemble(measured_sets, "exact", POSITIVES)

    assert moves(assembly.tree) == [
        (None, "K"),
        (CombineOp.INTERSECT, "M"),
        (CombineOp.INTERSECT, "R"),
    ]
    assert assembly.recovered == frozenset(POSITIVES)
    assert assembly.admitted == frozenset({NEGATIVES[3]})


def test_a_tie_goes_to_the_smaller_result() -> None:
    measured_sets = [
        measured("K", range(10), [0, 1], 100),
        measured("S", range(10), [2, 3, 4], 800),
        measured("T", range(10), [5, 6, 7], 300),
    ]

    assembly = assemble(measured_sets, "exact", POSITIVES)

    assert moves(assembly.tree) == [(None, "K"), (CombineOp.INTERSECT, "T")]
    assert assembly.admitted == frozenset()


def test_no_intersect_drops_a_recovered_positive() -> None:
    """D would remove both negatives but loses a positive, so it is not taken."""
    measured_sets = [
        measured("B", range(10), [6, 7], 900),
        measured("D", range(9), [], 200),
    ]

    assembly = assemble(measured_sets, "exact", POSITIVES)

    assert moves(assembly.tree) == [(None, "B")]
    assert assembly.admitted == frozenset(NEGATIVES[6:])


def test_cover_unions_the_candidates_that_add_the_most_positives() -> None:
    measured_sets = [
        measured("U", range(6), [], 300),
        measured("V", range(4, 10), [], 200),
        measured("W", range(5, 10), [], 400),
    ]

    assembly = assemble(measured_sets, "exact", POSITIVES)

    assert moves(assembly.tree) == [(None, "V"), (CombineOp.UNION, "U")]
    assert assembly.recovered == frozenset(POSITIVES)


def test_full_recall_candidates_rank_by_negatives_then_size() -> None:
    measured_sets = [
        measured("X", range(10), [0], 900),
        measured("Y", range(10), [0], 100),
        measured("Z", range(10), [], 5000),
    ]

    assert [m.candidate.id for m in rank(measured_sets)] == ["Z", "Y", "X"]
    assert moves(assemble(measured_sets, "exact", POSITIVES).tree) == [(None, "Z")]


def test_refinement_stops_at_the_first_intersect_that_removes_none() -> None:
    measured_sets = [
        measured("K", range(10), [0, 1], 100),
        measured("W", range(10), [0, 1, 2], 300),
    ]

    assembly = assemble(measured_sets, "exact", POSITIVES)

    assert moves(assembly.tree) == [(None, "K")]

"""A search that holds negatives and a few positives is subtracted as a branch."""

import pytest
from tests._support.separation_sets import POSITIVES, measured
from veupathdb.domain.strategy import CombineOp

from veupathdb_mcp.separation import SeparationNode
from veupathdb_mcp.separation import assemble as assembly_module
from veupathdb_mcp.separation.assemble import assemble

type Shape = str | tuple[CombineOp | None, Shape, Shape]


def _shape(node: SeparationNode) -> Shape:
    if node.kind == "leaf":
        return str(node.candidate_id)
    left, right = node.inputs
    return (node.operator, _shape(left), _shape(right))


def shape(node: SeparationNode | None) -> Shape | None:
    return None if node is None else _shape(node)


COVER = measured("B", range(10), [4, 5, 6, 7], 900)
NOISY = measured("E", [0], [2, 3, 4, 5, 6, 7], 300)
HOLDER = measured("R", range(5), [], 100)


def test_the_noisy_search_is_subtracted_less_the_search_that_holds_its_positive() -> (
    None
):
    assembly = assemble([COVER, NOISY, HOLDER], "exact", POSITIVES)

    assert [m.informs for m in (COVER, NOISY, HOLDER)] == [
        "recovering",
        "excluding",
        "recovering",
    ]
    assert shape(assembly.tree) == (
        CombineOp.MINUS,
        "B",
        (CombineOp.MINUS, "E", "R"),
    )
    assert assembly.recovered == frozenset(POSITIVES)
    assert assembly.admitted == frozenset()


def test_two_noisy_searches_are_subtracted_where_they_overlap() -> None:
    other = measured("F", [1], [3, 4, 5, 6, 7], 200)

    assembly = assemble([COVER, NOISY, other], "exact", POSITIVES)

    assert other.informs == "excluding"
    assert shape(assembly.tree) == (
        CombineOp.MINUS,
        "B",
        (CombineOp.INTERSECT, "F", "E"),
    )
    assert assembly.recovered == frozenset(POSITIVES)
    assert assembly.admitted == frozenset()


def test_a_single_search_that_removes_as_many_goes_first() -> None:
    clean = measured("C", [], [4, 5, 6, 7], 400)

    assembly = assemble([COVER, NOISY, HOLDER, clean], "exact", POSITIVES)

    assert shape(assembly.tree) == (CombineOp.MINUS, "B", "C")
    assert assembly.admitted == frozenset()


def test_similar_mode_subtracts_no_branch() -> None:
    assembly = assemble([COVER, NOISY, HOLDER], "similar", POSITIVES)

    assert shape(assembly.tree) == "B"


def test_a_branch_needs_room_for_both_its_searches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(assembly_module, "MAX_CRITERIA", 2)

    assembly = assemble([COVER, NOISY, HOLDER], "exact", POSITIVES)

    assert shape(assembly.tree) == "B"
    assert len(assembly.admitted) == 4

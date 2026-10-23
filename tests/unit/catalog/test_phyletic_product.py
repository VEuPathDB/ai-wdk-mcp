import pytest
from tests._support.phyletic_truth import synthetic_tree
from veupathdb.errors import ValidationError

from veupathdb_mcp.catalog.phyletic_logic import (
    CALL_SECONDS,
    SECONDS_PER_PAIR,
    Atom,
    Guard,
    Probe,
    Writing,
    both,
)
from veupathdb_mcp.catalog.phyletic_pattern import AllOf
from veupathdb_mcp.catalog.site_cost import SiteCost, site_cost

TREE = synthetic_tree()
TOP = 16_000


def _same_side_compares() -> AllOf:
    return AllOf.model_validate(
        {
            "kind": "all_of",
            "terms": [
                {
                    "kind": "compare",
                    "left": {"kind": "codes", "codes": [left]},
                    "right": {"kind": "codes", "codes": ["YB"]},
                    "reading": "totals",
                    "condition": condition,
                }
                for left, condition in (("xba", "more_than"), ("xaa", "at_least"))
            ],
        }
    )


def test_two_compares_over_one_side_try_pairs_linear_in_the_count() -> None:
    guard = Guard(TREE, site_cost(), 0)
    writing = Writing(TREE, {Probe(("YB",), "AND"): TOP}, guard)

    dnf = _same_side_compares().dnf(writing)

    assert len(dnf) == TOP + 1
    assert guard.pairs == 6 * (TOP + 1)


class _Recording(Guard):
    def __init__(self, cost: SiteCost) -> None:
        super().__init__(TREE, cost, 0)
        self.admitted: list[int] = []

    def admit(self, characters: int, terms: int, *, partial: bool = False) -> None:
        self.admitted.append(terms)
        super().admit(characters, terms, partial=partial)


def test_a_product_past_the_pair_budget_is_refused_before_it_builds() -> None:
    spare = 0.01
    guard = _Recording(
        SiteCost(fixed=CALL_SECONDS - spare, per_character=1e-9, longest=10**9)
    )
    left = tuple((one,) for one in _exact("xaa"))
    right = tuple((one,) for one in _exact("xab"))

    with pytest.raises(ValidationError) as refused:
        both([left, right], guard)

    assert guard.admitted == list(range(1, 201))
    assert guard.pairs == 200 + 200 * 200
    assert spare < 200 * 200 * SECONDS_PER_PAIR
    assert (refused.value.detail or "").startswith(
        f"Multiplied out, the pattern tries at least {200 + 200 * 200} clause pairs"
    )


def _exact(genome: str) -> list[Atom]:
    return [Atom(frozenset({genome}), False, k, k) for k in range(200)]


def test_pair_time_takes_its_share_of_the_character_cap() -> None:
    guard = Guard(TREE, site_cost(), 0)
    before = guard.characters

    guard.charge(int(250 / SECONDS_PER_PAIR))

    assert guard.characters < before
    assert guard.seconds(guard.characters) <= CALL_SECONDS

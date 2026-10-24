import re
from collections.abc import Callable, Iterator
from itertools import combinations

import pytest
from pydantic import TypeAdapter
from pydantic import ValidationError as PydanticValidationError
from tests._support.group_count_site import install
from tests._support.phyletic_truth import synthetic_tree, wide_tree
from veupathdb import JSONObject
from veupathdb.errors import ValidationError

from veupathdb_mcp.catalog import (
    PhyleticPattern,
    phyletic_builder,
    write_phyletic_expression,
)
from veupathdb_mcp.catalog.phyletic_builder import READS_PER_PROBE
from veupathdb_mcp.catalog.phyletic_logic import (
    CALL_SECONDS,
    HOST_MARGIN,
    MEASURED_SECONDS_PER_ATOM,
    SECONDS_PER_ATOM,
    Dnf,
    Guard,
    atom,
    either,
)
from veupathdb_mcp.catalog.phyletic_pattern import MAX_DEPTH, MAX_PATTERN_TERMS
from veupathdb_mcp.catalog.site_cost import SiteCost, site_cost

PATTERN: TypeAdapter[PhyleticPattern] = TypeAdapter(PhyleticPattern)
LETTERS = "abcdefghijklmnopqrstuvwxyz"
CEILING = site_cost().reads_within(CALL_SECONDS)


def _absent(code: str) -> JSONObject:
    return {
        "kind": "count",
        "of": {"kind": "codes", "codes": [code]},
        "condition": "absent",
    }


def _sides(count: int) -> JSONObject:
    pairs = list(combinations(LETTERS[:25], 2))[:count]
    return {
        "kind": "any_of",
        "terms": [
            {
                "kind": "compare",
                "left": {"kind": "codes", "codes": ["wz"]},
                "right": {"kind": "codes", "codes": [f"w{a}", f"w{b}"]},
                "reading": "totals",
                "condition": "more_than",
            }
            for a, b in pairs
        ],
    }


def _below(top: int) -> Callable[[str], int]:
    def answer(expression: str) -> int:
        probe = re.fullmatch(r"w[a-y]\+w[a-y]>=(\d+)", expression)
        if probe is None:
            return 1
        return 1 if int(probe[1]) <= top else 0

    return answer


def test_the_read_ceiling_leaves_the_longest_count_in_the_budget() -> None:
    cost = site_cost()

    assert READS_PER_PROBE == 25
    assert (
        cost.seconds(cost.longest, CEILING)
        <= CALL_SECONDS
        < cost.seconds(cost.longest, CEILING + 1)
    )


async def test_too_many_compare_sides_are_refused_before_any_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sides = CEILING // READS_PER_PROBE + 1
    site = install(monkeypatch, lambda expression: 1, wide_tree(26))

    with pytest.raises(ValidationError) as refused:
        await write_phyletic_expression(
            "orthomcl", PATTERN.validate_python(_sides(sides))
        )

    assert site.sent == []
    assert (refused.value.detail or "").startswith(
        f"The pattern compares {sides} distinct sides, and finding their largest "
        f"counts takes up to {sides * READS_PER_PROBE} count reads"
    )


async def test_the_most_compare_sides_the_budget_allows_are_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sides = CEILING // READS_PER_PROBE
    site = install(monkeypatch, _below(70), wide_tree(26))

    result = await write_phyletic_expression(
        "orthomcl", PATTERN.validate_python(_sides(sides))
    )

    assert result.maximum_reads == len(site.sent) - 1 == sides * 8


async def test_the_read_ceiling_holds_when_the_prediction_is_wrong(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(phyletic_builder, "READS_PER_PROBE", 1)
    sides = CEILING // READS_PER_PROBE + 1
    site = install(monkeypatch, _below(2**16 - 1), wide_tree(26))

    with pytest.raises(ValidationError) as refused:
        await write_phyletic_expression(
            "orthomcl", PATTERN.validate_python(_sides(sides))
        )

    assert len(site.sent) == CEILING
    assert (refused.value.detail or "").startswith(
        f"Finding the largest counts the pattern compares needs more than {CEILING} "
        "count reads"
    )


def _nested(depth: int) -> JSONObject:
    pattern = _absent("XA")
    for _ in range(depth - 1):
        pattern = {"kind": "all_of", "terms": [pattern]}
    return pattern


def test_a_pattern_nests_up_to_its_depth_bound() -> None:
    PATTERN.validate_python(_nested(MAX_DEPTH))

    with pytest.raises(PydanticValidationError, match=f"deeper than {MAX_DEPTH}"):
        PATTERN.validate_python(_nested(MAX_DEPTH + 1))


def test_a_pattern_holds_up_to_its_term_bound() -> None:
    PATTERN.validate_python(
        {"kind": "any_of", "terms": [_absent("XA")] * (MAX_PATTERN_TERMS - 1)}
    )

    with pytest.raises(
        PydanticValidationError, match=f"more than {MAX_PATTERN_TERMS} terms"
    ):
        PATTERN.validate_python(
            {"kind": "any_of", "terms": [_absent("XA")] * MAX_PATTERN_TERMS}
        )


def test_the_term_bound_counts_every_nested_term() -> None:
    half = {"kind": "any_of", "terms": [_absent("XA")] * (MAX_PATTERN_TERMS // 2)}

    with pytest.raises(
        PydanticValidationError, match=f"more than {MAX_PATTERN_TERMS} terms"
    ):
        PATTERN.validate_python({"kind": "all_of", "terms": [half, half]})


class _Counting(Guard):
    def __init__(self, cost: SiteCost) -> None:
        super().__init__(synthetic_tree(), cost, 0)
        self.admitted: list[tuple[int, int]] = []

    def admit(
        self, characters: int, terms: int, *, atoms: int = 0, partial: bool = False
    ) -> None:
        self.admitted.append((characters, terms))
        super().admit(characters, terms, atoms=atoms, partial=partial)


def test_either_refuses_at_the_first_clause_past_the_cap() -> None:
    guard = _Counting(SiteCost(fixed=0.0, per_character=0.5, longest=600))
    built: list[int] = []

    def parts() -> Iterator[Dnf]:
        for k in range(1, 1001):
            built.append(k)
            yield atom(frozenset({"xaa"}), (k, k), taxa=False)

    with pytest.raises(ValidationError):
        either(parts(), guard)

    held = guard.admitted
    assert [terms for _, terms in held] == list(range(1, len(held) + 1))
    assert held[-2][0] <= guard.characters < held[-1][0]
    assert len(built) == len(held) < 1000


async def test_the_largest_count_a_side_can_hold_takes_the_predicted_reads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = install(monkeypatch, _below(2**16 - 1), wide_tree(26))

    with pytest.raises(ValidationError):
        await write_phyletic_expression(
            "orthomcl", PATTERN.validate_python(_sides(1)["terms"][0])
        )

    assert len(site.sent) == READS_PER_PROBE


def test_a_budget_shorter_than_the_longest_count_allows_no_reads() -> None:
    assert site_cost().reads_within(90.0) == 0


def test_the_atom_cost_carries_a_margin_over_the_measured_cost() -> None:
    assert SECONDS_PER_ATOM == MEASURED_SECONDS_PER_ATOM * HOST_MARGIN
    assert HOST_MARGIN >= 2

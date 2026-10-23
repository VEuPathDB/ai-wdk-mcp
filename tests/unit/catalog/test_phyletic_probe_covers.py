import re
import threading
from collections.abc import Callable

import pytest
from pydantic import TypeAdapter
from tests._support.group_count_site import install
from tests._support.phyletic_truth import wide_tree
from veupathdb import JSONObject
from veupathdb.domain.parameters import PhyleticTree
from veupathdb.errors import ValidationError

from veupathdb_mcp.catalog import (
    PhyleticPattern,
    phyletic_builder,
    phyletic_logic,
    write_phyletic_expression,
)
from veupathdb_mcp.catalog.phyletic_logic import CALL_SECONDS, SECONDS_PER_COVER
from veupathdb_mcp.catalog.site_cost import SiteCost

PATTERN: TypeAdapter[PhyleticPattern] = TypeAdapter(PhyleticPattern)
WIDE = wide_tree(26)
LETTERS = "abcdefghijklmnopqrstuvwxyz"


class _Covers:
    def __init__(self) -> None:
        self.read: list[frozenset[str]] = []
        self.on_the_loop: list[frozenset[str]] = []
        self.cover = phyletic_logic.cover

    def __call__(self, tree: PhyleticTree, genomes: frozenset[str]) -> str:
        self.read.append(genomes)
        if threading.current_thread() is threading.main_thread():
            self.on_the_loop.append(genomes)
        return self.cover(tree, genomes)


def _counted(monkeypatch: pytest.MonkeyPatch) -> _Covers:
    covers = _Covers()
    monkeypatch.setattr(phyletic_logic, "cover", covers)
    return covers


def _compare(right: str) -> JSONObject:
    return {
        "kind": "compare",
        "left": {"kind": "codes", "codes": ["wa"]},
        "right": {"kind": "codes", "codes": [right]},
        "reading": "totals",
        "condition": "more_than",
    }


def _below(top: int) -> Callable[[str], int]:
    def answer(expression: str) -> int:
        probe = re.fullmatch(r"\w+>=(\d+)", expression)
        return 1 if probe is None or int(probe[1]) <= top else 0

    return answer


async def test_probe_covers_are_charged_off_the_event_loop_before_any_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    covers = _counted(monkeypatch)
    spare = 5.5 * SECONDS_PER_COVER
    monkeypatch.setattr(
        phyletic_builder,
        "site_cost",
        lambda: SiteCost(fixed=CALL_SECONDS - spare, per_character=1e-9, longest=1),
    )
    site = install(monkeypatch, _below(200), WIDE)
    pattern = PATTERN.validate_python(
        {"kind": "any_of", "terms": [_compare(f"w{letter}") for letter in LETTERS[1:]]}
    )

    with pytest.raises(ValidationError) as refused:
        await write_phyletic_expression("orthomcl", pattern)

    assert len(covers.read) == 5
    assert covers.on_the_loop == []
    assert site.sent == []
    assert (refused.value.detail or "").startswith(
        "The pattern names at least 6 distinct genome sets"
    )


async def test_a_cover_read_for_a_probe_is_not_read_again_in_the_build(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    covers = _counted(monkeypatch)
    install(monkeypatch, _below(3), WIDE)

    result = await write_phyletic_expression(
        "orthomcl", PATTERN.validate_python(_compare("wz"))
    )

    assert result.expression == (
        "wz=0 AND wa>=1 OR wz=1 AND wa>=2 OR wz=2 AND wa>=3 OR wz=3 AND wa>=4"
    )
    assert sorted(covers.read, key=sorted) == [frozenset({"wa"}), frozenset({"wz"})]
    assert covers.on_the_loop == []


class _ReadClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


async def test_the_time_spent_reading_shortens_the_build(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = _ReadClock()
    monkeypatch.setattr(phyletic_logic, "monotonic", clock)
    below = _below(3)

    def slow(expression: str) -> int:
        clock.now += 40.0
        return below(expression)

    site = install(monkeypatch, slow, WIDE)

    with pytest.raises(ValidationError) as refused:
        await write_phyletic_expression(
            "orthomcl", PATTERN.validate_python(_compare("wz"))
        )

    assert len(site.sent) == 8
    assert all(re.fullmatch(r"wz>=\d+", sent) for sent in site.sent)
    assert (refused.value.detail or "").startswith("The pattern's call ran 320 s")

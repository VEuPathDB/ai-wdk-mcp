from collections.abc import Callable, Iterable

import pytest
from tests._support.phyletic_truth import synthetic_tree, wide_tree
from veupathdb.domain.parameters import PhyleticTree
from veupathdb.errors import ValidationError

from veupathdb_mcp.catalog import phyletic_logic
from veupathdb_mcp.catalog.phyletic_logic import (
    CALL_SECONDS,
    SECONDS_PER_ATOM,
    SECONDS_PER_COVER,
    Atom,
    Clause,
    Guard,
    Probe,
    Writing,
    both,
    render,
)
from veupathdb_mcp.catalog.phyletic_pattern import AllOf, CountTerm
from veupathdb_mcp.catalog.site_cost import SiteCost, site_cost

TREE = synthetic_tree()
TOP = 16_000
WIDE = wide_tree(26)
VALUES = 60


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
    assert guard.atoms == 27 * (TOP + 1) - 5


class _Recording(Guard):
    def __init__(self, cost: SiteCost) -> None:
        super().__init__(TREE, cost, 0)
        self.admitted: list[int] = []

    def admit(
        self, characters: int, terms: int, *, atoms: int = 0, partial: bool = False
    ) -> None:
        self.admitted.append(terms)
        super().admit(characters, terms, atoms=atoms, partial=partial)


def test_a_product_past_the_atom_budget_is_refused_before_it_builds() -> None:
    spare = 0.01 + SECONDS_PER_COVER
    guard = _Recording(
        SiteCost(fixed=CALL_SECONDS - spare, per_character=1e-9, longest=10**9)
    )
    left = tuple((one,) for one in _exact("xaa"))
    right = tuple((one,) for one in _exact("xab"))

    with pytest.raises(ValidationError) as refused:
        both([left, right], guard)

    assert guard.admitted == list(range(1, 201))
    assert guard.atoms == 2 * 200 + 2 * 200 * 200
    assert spare < 2 * 200 * 200 * SECONDS_PER_ATOM
    assert (refused.value.detail or "").startswith(
        f"Multiplied out, the pattern tries at least {2 * 200 + 2 * 200 * 200} clause atoms"
    )


def _exact(genome: str) -> list[Atom]:
    return [Atom(frozenset({genome}), False, k, k) for k in range(200)]


def _wide_clauses() -> AllOf:
    side = {
        "kind": "any_of",
        "terms": [
            {
                "kind": "count",
                "of": {"kind": "each_genome_of", "codes": ["WD"]},
                "measure": "proteins",
                "condition": "at_least",
                "value": value,
            }
            for value in range(1, VALUES + 1)
        ],
    }
    return AllOf.model_validate({"kind": "all_of", "terms": [side, side]})


def test_wide_clauses_are_charged_by_their_atoms_before_they_build(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tried: list[int] = []
    clause = phyletic_logic._clause

    def counted(atoms: Iterable[Atom]) -> Clause | None:
        tried.append(1)
        return clause(atoms)

    monkeypatch.setattr(phyletic_logic, "_clause", counted)
    spare = 100_000 * SECONDS_PER_ATOM + 26 * SECONDS_PER_COVER
    guard = Guard(
        WIDE, SiteCost(fixed=CALL_SECONDS - spare, per_character=1e-9, longest=10**9), 0
    )
    terms = 2 * VALUES
    term_atoms = sum(range(1, 27))
    pairs = 26 * terms + VALUES + VALUES * VALUES
    atoms = 2 * term_atoms * terms + 4 * 26 * VALUES + 2 * 26 * VALUES * VALUES

    with pytest.raises(ValidationError) as refused:
        _wide_clauses().dnf(Writing(WIDE, {}, guard))

    assert guard.atoms == atoms
    assert len(tried) == pairs - VALUES * VALUES
    covers = 26 * SECONDS_PER_COVER
    assert pairs * 2 * SECONDS_PER_ATOM + covers < spare
    assert spare < atoms * SECONDS_PER_ATOM + covers
    assert (refused.value.detail or "").startswith(
        f"Multiplied out, the pattern tries at least {atoms} clause atoms"
    )


def test_atom_time_takes_its_share_of_the_character_cap() -> None:
    guard = Guard(TREE, site_cost(), 0)
    before = guard.characters

    guard.charge(int(250 / SECONDS_PER_ATOM))

    assert guard.characters < before
    assert guard.seconds(guard.characters) <= CALL_SECONDS


class _Clock:
    def __init__(self, *readings: float) -> None:
        self.readings = list(readings)

    def __call__(self) -> float:
        return self.readings.pop(0)


def _late(probes: int, now: float, monkeypatch: pytest.MonkeyPatch) -> Guard:
    monkeypatch.setattr(phyletic_logic, "monotonic", _Clock(1000.0, now))
    return Guard(TREE, SiteCost(fixed=10.0, per_character=1e-9, longest=10**9), probes)


def _charge(guard: Guard) -> None:
    guard.charge(0)


def _admit(guard: Guard) -> None:
    guard.admit(0, 0)


STEPS = pytest.mark.parametrize("step", [_charge, _admit], ids=["charge", "admit"])


@STEPS
def test_every_step_is_refused_once_the_deadline_passes(
    step: Callable[[Guard], None], monkeypatch: pytest.MonkeyPatch
) -> None:
    guard = _late(100, 1291.0, monkeypatch)

    with pytest.raises(ValidationError) as refused:
        step(guard)

    assert refused.value.detail == (
        "The pattern's call ran 291 s, past the 290 s the 300 s call budget leaves "
        "it before its count. Narrow the pattern: fewer terms under all_of, or "
        "compares over sides with smaller counts."
    )


@STEPS
def test_a_step_before_the_deadline_is_admitted(
    step: Callable[[Guard], None], monkeypatch: pytest.MonkeyPatch
) -> None:
    guard = _late(100, 1289.0, monkeypatch)

    step(guard)

    assert guard.atoms == 0


def test_the_deadline_stops_a_build_the_estimates_admit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ticks = iter(range(0, 10**9, 7))
    monkeypatch.setattr(phyletic_logic, "monotonic", lambda: float(next(ticks)))
    monkeypatch.setattr(phyletic_logic, "SECONDS_PER_ATOM", 0.0)
    guard = Guard(TREE, SiteCost(fixed=0.0, per_character=1e-12, longest=10**9), 0)
    writing = Writing(TREE, {Probe(("YB",), "AND"): TOP}, guard)

    with pytest.raises(ValidationError) as refused:
        _same_side_compares().dnf(writing)

    assert (refused.value.detail or "").startswith(
        "The pattern's call ran 301 s, past the 300 s the 300 s call budget leaves "
        "it before its count."
    )
    assert next(ticks) == 308


def test_distinct_sets_are_refused_before_their_covers_are_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    read: list[frozenset[str]] = []
    cover = phyletic_logic.cover

    def counted(tree: PhyleticTree, genomes: frozenset[str]) -> str:
        read.append(genomes)
        return cover(tree, genomes)

    monkeypatch.setattr(phyletic_logic, "cover", counted)
    spare = 5.5 * SECONDS_PER_COVER
    guard = Guard(
        WIDE, SiteCost(fixed=CALL_SECONDS - spare, per_character=1e-9, longest=10**9), 0
    )
    each = CountTerm.model_validate(
        {
            "kind": "count",
            "of": {"kind": "each_genome_of", "codes": ["WD"]},
            "measure": "proteins",
            "condition": "at_most",
            "value": 1,
        }
    )

    with pytest.raises(ValidationError) as refused:
        each.dnf(Writing(WIDE, {}, guard))

    assert len(read) == 5
    assert guard.covers == 6
    assert (refused.value.detail or "").startswith(
        "The pattern names at least 6 distinct genome sets"
    )


def test_an_admitted_clause_charges_its_atoms() -> None:
    guard = Guard(TREE, site_cost(), 0)

    guard.admit(10, 1, atoms=3)

    assert guard.atoms == 3


def test_the_rendering_charges_every_unit_it_writes() -> None:
    guard = Guard(TREE, site_cost(), 0)
    clause = (
        Atom(frozenset({"xaa"}), False, 0, 2),
        Atom(frozenset({"xab"}), False, 0, 0),
    )

    text, terms = render((clause,), guard)

    assert (text, terms) == ("xaa=0 AND xab=0 OR xaa<=2 AND xab=0", 2)
    assert guard.atoms == 4


def test_the_deadline_counts_from_the_start_it_is_given(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(phyletic_logic, "monotonic", _Clock(1291.0))
    guard = Guard(
        TREE, SiteCost(fixed=10.0, per_character=1e-9, longest=10**9), 0, start=1000.0
    )

    with pytest.raises(ValidationError) as refused:
        guard.charge(0)

    assert (refused.value.detail or "").startswith("The pattern's call ran 291 s")


def test_the_build_keeps_the_deadline_of_the_probe_step(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(phyletic_logic, "monotonic", _Clock(1000.0, 1500.0))
    probing = Guard(TREE, SiteCost(fixed=10.0, per_character=1e-9, longest=10**9), 0)

    building = probing.after(100)

    assert (building.start, building.deadline) == (1000.0, 1290.0)

from collections import Counter
from fractions import Fraction

import pytest
from tests._support.group_cloud_site import cloud_counts
from tests._support.phyletic_truth import holds, synthetic_groups, synthetic_tree
from veupathdb import JSONObject

from veupathdb_mcp.catalog import (
    AbsentGroupsCompareError,
    CompareTerm,
    SideCounts,
    compare_counts,
    is_group_id,
    is_residual,
)
from veupathdb_mcp.catalog.phyletic_compare import summed
from veupathdb_mcp.catalog.phyletic_logic import Condition
from veupathdb_mcp.catalog.phyletic_pattern import Reading

TGON = cloud_counts("r02_tgon_groupcloud")
PFAL = cloud_counts("r02_pfal_groupcloud")
TOX = cloud_counts("r03_tox_groupcloud")
PLAS = cloud_counts("r04_plas_groupcloud")


def _genome(counts: Counter[str]) -> SideCounts:
    return SideCounts(genomes=1, totals=counts, per_genome=(counts,))


@pytest.mark.parametrize("reading", ["per_genome", "totals", "averages"])
def test_one_genome_against_one_reproduces_the_expression_ladder(
    reading: Reading,
) -> None:
    compared = compare_counts(
        _genome(TGON), _genome(PFAL), reading, "more_than", Fraction(1)
    )

    assert len(compared.groups) == 3896
    assert (len(compared.both), len(compared.left_only)) == (362, 3534)
    assert compared.right_only == ()


def test_the_genus_means_compare_over_the_groups_both_sets_hold() -> None:
    tox = SideCounts(genomes=15, totals=TOX)
    plas = SideCounts(genomes=61, totals=PLAS)

    above = compare_counts(tox, plas, "averages", "more_than", Fraction(1))
    double = compare_counts(tox, plas, "averages", "more_than", Fraction(2))
    below = compare_counts(tox, plas, "averages", "fewer_than", Fraction(1))

    assert (len(above.both), len(above.left_only), len(above.right_only)) == (
        1884,
        5480,
        0,
    )
    assert len(above.groups) == 1884 + 5480
    assert (len(double.both), len(double.left_only)) == (317, 5480)
    assert len(below.right_only) == 6862
    assert len(below.both) == 2534 - 1884 - 371
    assert above.ties == 371
    assert above.residual == sum(group.startswith("OGR") for group in above.groups)
    assert above.residual == 1 + 1968


@pytest.mark.parametrize("condition", ["at_least", "at_most", "exactly"])
def test_a_compare_that_holds_at_zero_against_zero_is_refused(
    condition: Condition,
) -> None:
    side = SideCounts(genomes=1, totals=TGON, per_genome=(TGON,))

    with pytest.raises(AbsentGroupsCompareError) as refused:
        compare_counts(side, side, "totals", condition, Fraction(1))

    assert "neither set holds" in (refused.value.detail or "")


_TREE = synthetic_tree()
_GROUPS = synthetic_groups()
_SETS = [
    ({"kind": "codes", "codes": ["XG"]}, {"kind": "all_except", "codes": ["XA"]}),
    ({"kind": "codes", "codes": ["xaa", "yba"]}, {"kind": "codes", "codes": ["YB"]}),
    ({"kind": "codes", "codes": ["zza"]}, {"kind": "codes", "codes": ["xba"]}),
]


def _side(genomes: frozenset[str], ids: list[str]) -> SideCounts:
    per_genome = tuple(
        Counter(
            {
                ident: group[genome]
                for ident, group in zip(ids, _GROUPS, strict=True)
                if group.get(genome, 0) > 0
            }
        )
        for genome in sorted(genomes)
    )
    return SideCounts(
        genomes=len(genomes), totals=summed(per_genome), per_genome=per_genome
    )


@pytest.mark.parametrize("sets", _SETS)
@pytest.mark.parametrize("reading", ["per_genome", "totals", "averages"])
@pytest.mark.parametrize(
    ("condition", "factor"), [("more_than", 1), ("more_than", 1.5), ("fewer_than", 2)]
)
def test_the_computed_groups_are_the_groups_the_pattern_selects(
    sets: tuple[JSONObject, JSONObject],
    reading: Reading,
    condition: Condition,
    factor: float,
) -> None:
    term = CompareTerm.model_validate(
        {
            "kind": "compare",
            "left": sets[0],
            "right": sets[1],
            "reading": reading,
            "condition": condition,
            "factor": factor,
        }
    )
    ids = [f"OG8_{index:07d}" for index in range(len(_GROUPS))]
    left, right = term.left.genomes(_TREE), term.right.genomes(_TREE)

    compared = compare_counts(
        _side(left, ids), _side(right, ids), reading, condition, Fraction(str(factor))
    )

    selected = {
        ident
        for ident, group in zip(ids, _GROUPS, strict=True)
        if holds(term, group, _TREE)
    }
    assert set(compared.groups) == selected


def test_absent_genomes_count_zero_in_a_mean() -> None:
    left = SideCounts(genomes=4, totals=Counter({"OG8_0000001": 4}))
    right = SideCounts(genomes=1, totals=Counter({"OG8_0000001": 1}))

    tied = compare_counts(left, right, "averages", "more_than", Fraction(1))
    totals = compare_counts(left, right, "totals", "more_than", Fraction(1))

    assert (tied.groups, tied.ties) == ((), 1)
    assert totals.groups == ("OG8_0000001",)


@pytest.mark.parametrize(
    ("condition", "factor", "held"),
    [
        ("more_than", "1", ()),
        ("more_than", "0.5", ("OG8_0000001",)),
        ("fewer_than", "2", ()),
        ("fewer_than", "4", ("OG8_0000001",)),
    ],
)
def test_per_genome_holds_for_every_genome_of_each_side(
    condition: Condition, factor: str, held: tuple[str, ...]
) -> None:
    left = SideCounts(
        genomes=2,
        totals=Counter({"OG8_0000001": 5}),
        per_genome=(Counter({"OG8_0000001": 2}), Counter({"OG8_0000001": 3})),
    )
    right = SideCounts(
        genomes=2,
        totals=Counter({"OG8_0000001": 3}),
        per_genome=(Counter({"OG8_0000001": 2}), Counter({"OG8_0000001": 1})),
    )

    compared = compare_counts(left, right, "per_genome", condition, Fraction(factor))

    assert compared.groups == held


def test_a_per_genome_reading_without_genome_counts_is_refused() -> None:
    side = SideCounts(genomes=1, totals=Counter({"OG8_0000001": 1}))

    with pytest.raises(ValueError, match="needs each genome's counts"):
        compare_counts(side, side, "per_genome", "more_than", Fraction(1))


def test_genome_counts_match_the_genome_count() -> None:
    with pytest.raises(ValueError, match="1 genome counts for 2 genomes"):
        SideCounts(genomes=2, totals=Counter(), per_genome=(Counter(),))


@pytest.mark.parametrize(
    ("word", "group", "residual"),
    [
        ("OG8_0000011", True, False),
        ("OGR8r1_0000039", True, True),
        ("OG8r1_0000039", False, False),
        ("PF3D7_0100100", False, False),
        ("Too many words", False, False),
    ],
)
def test_a_group_id_is_core_or_residual(word: str, group: bool, residual: bool) -> None:
    assert (is_group_id(word), is_residual(word)) == (group, residual)

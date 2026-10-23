import operator
import random
from collections.abc import Callable, Mapping
from fractions import Fraction

from veupathdb.domain.parameters import PhyleticExpression, PhyleticTree, TaxonEntry

from veupathdb_mcp.catalog import (
    AllExcept,
    AllOf,
    AnyOf,
    CodeSet,
    CompareTerm,
    CountTerm,
    EachGenomeOf,
    EachSpeciesOf,
    NoneOf,
    PhyleticPattern,
)

type Group = Mapping[str, int]

_TAXA = (
    ("XA", None, "Clade X", True),
    ("XG", "XA", "Genus Xalpha", True),
    ("xaa", "XG", "Xalpha one A", False),
    ("xab", "XG", "Xalpha one B", False),
    ("xac", "XG", "Xalpha two A", False),
    ("xba", "XA", "Xbeta three A", False),
    ("YB", None, "Clade Y", True),
    ("yaa", "YB", "Ygamma four A", False),
    ("yab", "YB", "Ygamma four B", False),
    ("yac", "YB", "Ygamma four C", False),
    ("yba", "YB", "Ydelta five A", False),
    ("zza", None, "Zeta six A", False),
)

GENOMES = tuple(code for code, _, _, clade in _TAXA if not clade)


def wide_tree(genomes: int) -> PhyleticTree:
    return PhyleticTree.from_taxa(
        [
            TaxonEntry(id="WD", parent_id=None, code="WD", label="Clade W", clade=True),
            *(
                TaxonEntry(
                    id=f"w{index}",
                    parent_id="WD",
                    code="w" + "abcdefghijklmnopqrstuvwxyz"[index],
                    label=f"Wide {index} A",
                    clade=False,
                )
                for index in range(genomes)
            ),
        ]
    )


def synthetic_tree() -> PhyleticTree:
    return PhyleticTree.from_taxa(
        [
            TaxonEntry(id=code, parent_id=parent, code=code, label=label, clade=clade)
            for code, parent, label, clade in _TAXA
        ]
    )


def synthetic_groups(count: int = 300, seed: int = 7) -> tuple[dict[str, int], ...]:
    rng = random.Random(seed)
    drawn = [
        {
            genome: proteins
            for genome in GENOMES
            if (proteins := rng.choice((0, 0, 0, 1, 1, 2, 3, 4))) > 0
        }
        for _ in range(count)
    ]
    return ({}, dict.fromkeys(GENOMES, 1), dict.fromkeys(GENOMES, 4), *drawn)


_COMPARED: dict[str, Callable[[Fraction, Fraction], bool]] = {
    "at_least": operator.ge,
    "at_most": operator.le,
    "exactly": operator.eq,
    "more_than": operator.gt,
    "fewer_than": operator.lt,
}


def _named(tree: PhyleticTree, codes: list[str]) -> set[str]:
    return tree.genomes_under(codes)


def _parts(
    of: CodeSet | AllExcept | EachSpeciesOf | EachGenomeOf, tree: PhyleticTree
) -> list[set[str]]:
    match of:
        case CodeSet():
            return [_named(tree, of.codes)]
        case AllExcept():
            return [_named(tree, ["ALL"]) - _named(tree, of.codes)]
        case EachSpeciesOf():
            return [set(group.genomes) for group in tree.species_groups(of.codes)]
        case EachGenomeOf():
            return [{genome} for genome in _named(tree, of.codes)]


def _present(genomes: set[str], group: Group) -> int:
    return sum(1 for genome in genomes if group.get(genome, 0) > 0)


def _proteins(genomes: set[str], group: Group) -> int:
    return sum(group.get(genome, 0) for genome in genomes)


def _count_holds(term: CountTerm, genomes: set[str], group: Group) -> bool:
    if term.condition == "absent":
        return _present(genomes, group) == 0
    stated = Fraction(str(term.value))
    match term.measure:
        case "genomes":
            value, bound = Fraction(_present(genomes, group)), stated
        case "proteins":
            value, bound = Fraction(_proteins(genomes, group)), stated
        case "share":
            value = Fraction(_present(genomes, group) * 100)
            bound = stated * len(genomes)
    return _COMPARED[term.condition](value, bound)


def _compare_holds(term: CompareTerm, group: Group, tree: PhyleticTree) -> bool:
    [left] = _parts(term.left, tree)
    [right] = _parts(term.right, tree)
    factor = Fraction(str(term.factor))
    held = _COMPARED[term.condition]
    match term.reading:
        case "totals":
            return held(
                Fraction(_proteins(left, group)), factor * _proteins(right, group)
            )
        case "averages":
            return held(
                Fraction(_proteins(left, group), len(left)),
                factor * Fraction(_proteins(right, group), len(right)),
            )
        case "per_genome":
            return all(
                held(Fraction(group.get(a, 0)), factor * group.get(b, 0))
                for a in left
                for b in right
            )


def holds(pattern: PhyleticPattern, group: Group, tree: PhyleticTree) -> bool:
    match pattern:
        case CountTerm():
            return all(
                _count_holds(pattern, part, group) for part in _parts(pattern.of, tree)
            )
        case CompareTerm():
            return _compare_holds(pattern, group, tree)
        case AllOf():
            return all(holds(term, group, tree) for term in pattern.terms)
        case AnyOf():
            return any(holds(term, group, tree) for term in pattern.terms)
        case NoneOf():
            return not any(holds(term, group, tree) for term in pattern.terms)


def site_counts(
    tree: PhyleticTree, groups: tuple[dict[str, int], ...]
) -> Callable[[str], int]:
    def answer(expression: str) -> int:
        read = PhyleticExpression.parse(expression).site_reading().root
        return sum(1 for group in groups if read.holds_for(group, tree))

    return answer

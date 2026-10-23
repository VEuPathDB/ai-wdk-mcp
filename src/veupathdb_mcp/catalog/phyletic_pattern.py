from __future__ import annotations

from collections.abc import Mapping
from fractions import Fraction
from typing import Annotated, Literal, Self

from pydantic import ConfigDict, Field, model_validator
from veupathdb.domain.parameters import PHYLETIC_ROOT_CODE, PhyleticTree
from veupathdb.model import CamelModel

from veupathdb_mcp.catalog.phyletic_logic import (
    FALSE,
    Condition,
    Dnf,
    Guard,
    Probe,
    Writing,
    atom,
    both,
    bounds,
    either,
    neither,
    refuse,
)

Measure = Literal["genomes", "proteins", "share"]
Reading = Literal["per_genome", "totals", "averages"]

WHOLE = 100
MAX_DEPTH = 8
MAX_TERMS = 128

_CODES = Field(
    min_length=1,
    description="Clade or genome codes from lookup_phyletic_codes, read together.",
)


_LISTED = 6
_WORDS = {
    "at_least": "at least",
    "at_most": "at most",
    "exactly": "exactly",
    "more_than": "more than",
    "fewer_than": "fewer than",
}
_READINGS = {
    "per_genome": "each genome's",
    "totals": "the total",
    "averages": "the per-genome average",
}


def _listed(codes: list[str]) -> str:
    shown = ", ".join(codes[:_LISTED])
    rest = len(codes) - _LISTED
    return f"{shown} and {rest} more" if rest > 0 else shown


def _named(tree: PhyleticTree, codes: list[str]) -> frozenset[str]:
    unknown = sorted(set(codes) - tree.codes() - {PHYLETIC_ROOT_CODE})
    if unknown:
        refuse(f"These codes are not in the site's taxonomy: {unknown}.")
    held = frozenset(tree.genomes_under(codes))
    if not held:
        refuse(f"{codes} holds no genome.")
    return held


class CodeSet(CamelModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["codes"]
    codes: list[str] = _CODES

    def outline(self) -> str:
        return _listed(self.codes)

    def genomes(self, tree: PhyleticTree) -> frozenset[str]:
        return _named(tree, self.codes)

    def parts(self, tree: PhyleticTree) -> list[frozenset[str]]:
        return [self.genomes(tree)]


class AllExcept(CamelModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["all_except"]
    codes: list[str] = _CODES

    def outline(self) -> str:
        return f"every genome outside {_listed(self.codes)}"

    def genomes(self, tree: PhyleticTree) -> frozenset[str]:
        every = frozenset(tree.genomes_under([PHYLETIC_ROOT_CODE]))
        outside = every - _named(tree, self.codes)
        if not outside:
            refuse(f"all_except {self.codes} leaves no genome.")
        return outside

    def parts(self, tree: PhyleticTree) -> list[frozenset[str]]:
        return [self.genomes(tree)]


class EachSpeciesOf(CamelModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["each_species_of"]
    codes: list[str] = _CODES

    def outline(self) -> str:
        return f"each species of {_listed(self.codes)}"

    def parts(self, tree: PhyleticTree) -> list[frozenset[str]]:
        _named(tree, self.codes)
        return [frozenset(group.genomes) for group in tree.species_groups(self.codes)]


class EachGenomeOf(CamelModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["each_genome_of"]
    codes: list[str] = _CODES

    def outline(self) -> str:
        return f"each genome of {_listed(self.codes)}"

    def parts(self, tree: PhyleticTree) -> list[frozenset[str]]:
        return [frozenset({genome}) for genome in sorted(_named(tree, self.codes))]


type GenomeSet = Annotated[CodeSet | AllExcept, Field(discriminator="kind")]
type CountedSet = Annotated[
    CodeSet | AllExcept | EachSpeciesOf | EachGenomeOf, Field(discriminator="kind")
]

type Maxima = Mapping[Probe, int]


class CountTerm(CamelModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["count"]
    of: CountedSet
    measure: Measure | None = Field(
        default=None,
        description=(
            "genomes: genomes of the set holding a protein of the group; proteins: "
            "the group's proteins over the set; share: percent of the set's genomes "
            "holding a protein. Required unless condition is absent."
        ),
    )
    condition: Condition | Literal["absent"]
    value: float | None = Field(
        default=None,
        ge=0,
        description="The count, or the percent for share. Required unless absent.",
    )

    @model_validator(mode="after")
    def _stated(self) -> Self:
        if self.condition == "absent":
            if self.measure is not None or self.value is not None:
                msg = "absent takes no measure and no value."
                raise ValueError(msg)
            return self
        if self.measure is None or self.value is None:
            msg = f"{self.condition} needs a measure and a value."
            raise ValueError(msg)
        if self.measure == "share" and self.value > WHOLE:
            msg = "A share is a percent from 0 to 100."
            raise ValueError(msg)
        if self.measure != "share" and not self.value.is_integer():
            msg = f"A count of {self.measure} is a whole number."
            raise ValueError(msg)
        return self

    def depth(self) -> int:
        return 1

    def size(self) -> int:
        return 1

    def probes(self, guard: Guard) -> list[Probe]:
        self.of.parts(guard.tree)
        return []

    def outline(self) -> str:
        if self.measure is None or self.value is None or self.condition == "absent":
            return f"no protein in {self.of.outline()}"
        amount = (
            f"{self.value:g}% of genomes"
            if self.measure == "share"
            else f"{self.value:g} {self.measure}"
        )
        return f"{_WORDS[self.condition]} {amount} in {self.of.outline()}"

    def dnf(self, writing: Writing) -> Dnf:
        return both(
            (self._within(part) for part in self.of.parts(writing.tree)),
            writing.guard,
        )

    def _within(self, genomes: frozenset[str]) -> Dnf:
        if self.measure is None or self.value is None:
            return atom(genomes, bounds("absent", Fraction(0)), taxa=True)
        value = Fraction(str(self.value))
        if self.measure == "share":
            value = value * len(genomes) / WHOLE
        return atom(
            genomes, bounds(self.condition, value), taxa=self.measure != "proteins"
        )


class CompareTerm(CamelModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["compare"]
    left: GenomeSet
    right: GenomeSet
    reading: Reading = Field(
        description=(
            "per_genome: each genome of left against each genome of right; totals: "
            "the protein total of each set; averages: each set's proteins per genome."
        )
    )
    condition: Condition
    factor: float = Field(
        default=1, gt=0, description="left <condition> factor times right."
    )

    def _probe(self, guard: Guard) -> Probe:
        self.left.genomes(guard.tree)
        right = self.right.genomes(guard.tree)
        if self.reading != "per_genome" or len(right) == 1:
            return Probe((guard.unit(right),), "AND")
        upper = self.condition in {"at_least", "more_than"}
        return Probe(tuple(sorted(right)), "OR" if upper else "AND")

    def depth(self) -> int:
        return 1

    def size(self) -> int:
        return 1

    def probes(self, guard: Guard) -> list[Probe]:
        return [self._probe(guard)]

    def outline(self) -> str:
        return (
            f"{_READINGS[self.reading]} proteins of {self.left.outline()} "
            f"{_WORDS[self.condition]} {self.factor:g} times those of "
            f"{self.right.outline()}"
        )

    def dnf(self, writing: Writing) -> Dnf:
        tree, guard = writing.tree, writing.guard
        left = self.left.genomes(tree)
        right = self.right.genomes(tree)
        top = writing.maxima[self._probe(guard)]
        factor = Fraction(str(self.factor))
        if self.reading == "per_genome":
            return either(
                (
                    self._per_genome(left, right, factor, k, guard)
                    for k in range(top + 1)
                ),
                guard,
            )
        if self.reading == "averages":
            factor = factor * len(left) / len(right)
        return either(
            (
                both(
                    [
                        atom(right, (k, k), taxa=False),
                        atom(left, bounds(self.condition, factor * k), taxa=False),
                    ],
                    guard,
                )
                for k in range(top + 1)
            ),
            guard,
        )

    def _per_genome(
        self,
        left: frozenset[str],
        right: frozenset[str],
        factor: Fraction,
        k: int,
        guard: Guard,
    ) -> Dnf:
        match self.condition:
            case _ if len(right) == 1:
                span: tuple[int, int | None] = (k, k)
            case "at_least" | "more_than":
                span = (0, k)
            case "exactly":
                span = (k, k)
            case "at_most" | "fewer_than":
                span = (k, None)
        side = bounds(self.condition, factor * k)
        if side is None:
            return FALSE
        return both(
            [
                *(
                    atom(frozenset({genome}), span, taxa=False)
                    for genome in sorted(right)
                ),
                *(
                    atom(frozenset({genome}), side, taxa=False)
                    for genome in sorted(left)
                ),
            ],
            guard,
        )


class _Combination(CamelModel):
    model_config = ConfigDict(frozen=True)

    terms: list[PhyleticPattern] = Field(min_length=1, max_length=MAX_TERMS)

    def depth(self) -> int:
        return 1 + max(term.depth() for term in self.terms)

    def size(self) -> int:
        return 1 + sum(term.size() for term in self.terms)

    def probes(self, guard: Guard) -> list[Probe]:
        return [probe for term in self.terms for probe in term.probes(guard)]

    def _joined(self) -> str:
        return "; ".join(term.outline() for term in self.terms)

    @model_validator(mode="after")
    def _bounded(self) -> Self:
        if self.depth() > MAX_DEPTH:
            msg = f"A pattern nests no deeper than {MAX_DEPTH} levels."
            raise ValueError(msg)
        if self.size() > MAX_TERMS:
            msg = (
                f"A pattern holds no more than {MAX_TERMS} terms, nested ones counted."
            )
            raise ValueError(msg)
        return self


class AllOf(_Combination):
    kind: Literal["all_of"]

    def outline(self) -> str:
        return f"all of ({self._joined()})"

    def dnf(self, writing: Writing) -> Dnf:
        return both((term.dnf(writing) for term in self.terms), writing.guard)


class AnyOf(_Combination):
    kind: Literal["any_of"]

    def outline(self) -> str:
        return f"any of ({self._joined()})"

    def dnf(self, writing: Writing) -> Dnf:
        return either((term.dnf(writing) for term in self.terms), writing.guard)


class NoneOf(_Combination):
    kind: Literal["none_of"]

    def outline(self) -> str:
        return f"none of ({self._joined()})"

    def dnf(self, writing: Writing) -> Dnf:
        guard = writing.guard
        return neither(either((term.dnf(writing) for term in self.terms), guard), guard)


type PhyleticPattern = Annotated[
    CountTerm | CompareTerm | AllOf | AnyOf | NoneOf, Field(discriminator="kind")
]


_Combination.model_rebuild()
AllOf.model_rebuild()
AnyOf.model_rebuild()
NoneOf.model_rebuild()

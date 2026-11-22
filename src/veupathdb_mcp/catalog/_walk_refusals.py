"""The problems a parameter walk notes on every pass and raises once, in call order."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from veupathdb.domain.parameters import ParamGraph
from veupathdb.errors import ValidationError
from veupathdb.wdk import WDKParameter

from veupathdb_mcp.catalog.vocab_resolve import ResolveContext, gathered, ordered


def ancestors(parents: Mapping[str, tuple[str, ...]], name: str) -> set[str]:
    found: set[str] = set()
    waiting = list(parents.get(name, ()))
    while waiting:
        parent = waiting.pop()
        if parent not in found:
            found.add(parent)
            waiting.extend(parents.get(parent, ()))
    return found


@dataclass
class Refusals:
    problems: list[ValidationError] = field(default_factory=list)
    names: set[str] = field(default_factory=set)
    declared: dict[str, WDKParameter] = field(default_factory=dict)
    sources: dict[str, tuple[str, ...]] = field(default_factory=dict)

    def note(
        self,
        refusal: ValidationError,
        names: set[str],
        declarations: Sequence[WDKParameter] = (),
        *,
        derived_from: tuple[str, ...] = (),
    ) -> None:
        self.problems.append(refusal)
        self.names |= names
        self.declared |= {d.name: d for d in declarations if d.name in names}
        self.sources |= dict.fromkeys(names, derived_from) if derived_from else {}

    def note_miss(self, miss: ValidationError) -> None:
        self.problems.append(miss)

    def blocked(self, declarations: Sequence[WDKParameter]) -> set[str]:
        parents = ParamGraph.of(declarations).wire_parents
        return self.names | {
            d.name for d in declarations if ancestors(parents, d.name) & self.names
        }

    async def one(
        self, order: Sequence[str], about: ResolveContext | None
    ) -> ValidationError | None:
        if not self.problems:
            return None
        return await ordered(
            gathered(self.problems, order, self.sources),
            list(self.declared.values()),
            about,
        )

    async def raise_once(
        self, order: Sequence[str], about: ResolveContext | None
    ) -> None:
        refusal = await self.one(order, about)
        if refusal is not None:
            raise refusal

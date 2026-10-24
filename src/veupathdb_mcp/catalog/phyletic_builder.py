from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Literal

from pydantic import ConfigDict, Field
from veupathdb.domain.parameters import (
    PhyleticExpression,
    PhyleticTree,
    check_expression,
)
from veupathdb.model import CamelModel

from veupathdb_mcp.catalog.group_counts import GroupCountReports, site_taxonomy
from veupathdb_mcp.catalog.phyletic_logic import (
    CALL_SECONDS,
    Guard,
    PhyleticExpressionTooLargeError,
    PhyleticExpressionTooSlowError,
    Probe,
    Writing,
    admit_rendering,
    clock,
    refuse,
    render,
)
from veupathdb_mcp.catalog.phyletic_pattern import Maxima, PhyleticPattern
from veupathdb_mcp.catalog.site_cost import SECONDS_PER_PROBE, site_cost

FIRST_PROBE = 128
LAST_PROBE = 2**16
DOUBLING_READS = (LAST_PROBE // FIRST_PROBE).bit_length()
HALVING_READS = (LAST_PROBE // 2).bit_length() - 1
READS_PER_PROBE = DOUBLING_READS + HALVING_READS
READING_LIMIT = 2_000
_CUT = " ..."


class PhyleticExpressionResult(CamelModel):
    model_config = ConfigDict(frozen=True)

    route: Literal["expression"] = "expression"
    site_id: str
    expression: str
    reading: str
    groups: int = Field(ge=0)
    codes: tuple[str, ...] = Field(min_length=1)
    maximum_reads: int = Field(ge=0)


@dataclass(frozen=True, slots=True)
class _Written:
    text: str
    terms: int
    reading: str
    codes: tuple[str, ...]


def probed(pattern: PhyleticPattern, guard: Guard) -> list[Probe]:
    return list(dict.fromkeys(pattern.probes(guard)))


def written(
    pattern: PhyleticPattern, probing: Guard, maxima: Maxima, probes: int
) -> _Written:
    guard = probing.after(probes)
    tree = guard.tree
    text, terms = render(pattern.dnf(Writing(tree, maxima, guard)), guard)
    expression = PhyleticExpression.parse(text)
    check_expression(expression, tree)
    return _Written(
        text=text,
        terms=terms,
        reading=reading(pattern, expression, tree, text, terms),
        codes=tuple(expression.codes()),
    )


def reading(
    pattern: PhyleticPattern,
    expression: PhyleticExpression,
    tree: PhyleticTree,
    text: str,
    terms: int,
) -> str:
    if len(text) <= READING_LIMIT:
        described = expression.describe(tree)
        if len(described) <= READING_LIMIT:
            return described
    counted = f"; written as {terms} OR terms, {len(text)} characters"
    outline = pattern.outline()
    room = READING_LIMIT - len(counted)
    if len(outline) > room:
        outline = outline[: room - len(_CUT)] + _CUT
    return outline + counted


async def _largest(reports: GroupCountReports, probe: Probe) -> int:
    held, empty = 0, FIRST_PROBE
    while await reports.groups(probe.at(empty)) > 0:
        if empty == LAST_PROBE:
            refuse(f"{probe.at(empty)} still answers groups; no count is that large.")
        held, empty = empty, empty * 2
    while empty - held > 1:
        middle = (held + empty) // 2
        if await reports.groups(probe.at(middle)) > 0:
            held = middle
        else:
            empty = middle
    return held


def _admit_reads(probes: int, ceiling: int) -> None:
    predicted = probes * READS_PER_PROBE
    if predicted > ceiling:
        refuse(
            f"The pattern compares {probes} distinct sides, and finding their largest "
            f"counts takes up to {predicted} count reads, more than the {ceiling} the "
            f"{CALL_SECONDS} s call budget allows at {SECONDS_PER_PROBE} s a read. "
            "Narrow the pattern: compare fewer distinct sides."
        )


@dataclass(frozen=True, slots=True)
class Probed:
    probing: Guard
    probes: tuple[Probe, ...]
    maxima: Maxima
    reads: int


def least_expression(pattern: PhyleticPattern, guard: Guard) -> None:
    least = dict.fromkeys(probed(pattern, guard), 0)
    admit_rendering(pattern.dnf(Writing(guard.tree, least, guard)), guard)


async def admit_least_expression(site_id: str, pattern: PhyleticPattern) -> None:
    tree = await site_taxonomy(site_id)
    guard = Guard(tree, site_cost(), 0)
    await asyncio.to_thread(least_expression, pattern, guard)


async def least_expression_too_large(site_id: str, pattern: PhyleticPattern) -> bool:
    try:
        await admit_least_expression(site_id, pattern)
    except PhyleticExpressionTooLargeError, PhyleticExpressionTooSlowError:
        return True
    return False


async def probe_pattern(site_id: str, pattern: PhyleticPattern) -> Probed:
    start = clock()
    tree = await site_taxonomy(site_id)
    cost = site_cost()
    probing = Guard(tree, cost, 0, start=start)
    probes = await asyncio.to_thread(probed, pattern, probing)
    ceiling = cost.reads_within(CALL_SECONDS)
    _admit_reads(len(probes), ceiling)
    reports = GroupCountReports(site_id, ceiling)
    maxima = {probe: await _largest(reports, probe) for probe in probes}
    return Probed(probing, tuple(probes), maxima, reports.sent)


async def expression_of(
    site_id: str, pattern: PhyleticPattern, found: Probed
) -> PhyleticExpressionResult:
    built = await asyncio.to_thread(
        written, pattern, found.probing, found.maxima, found.reads
    )
    return PhyleticExpressionResult(
        site_id=site_id,
        expression=built.text,
        reading=built.reading,
        groups=await GroupCountReports(site_id, 1).groups(built.text),
        codes=built.codes,
        maximum_reads=found.reads,
    )


async def write_phyletic_expression(
    site_id: str, pattern: PhyleticPattern
) -> PhyleticExpressionResult:
    return await expression_of(site_id, pattern, await probe_pattern(site_id, pattern))

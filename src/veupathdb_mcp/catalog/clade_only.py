from __future__ import annotations

from collections.abc import Sequence

from pydantic import ConfigDict, Field
from veupathdb.domain.parameters import PhyleticNode, PhyleticTree
from veupathdb.errors import ValidationError
from veupathdb.model import CamelModel

from veupathdb_mcp.catalog.group_counts import GroupCountReports, site_taxonomy
from veupathdb_mcp.computed import computed

CLADE_ONLY_COUNT_REPORTS = 1


class CladeOnlyExpression(CamelModel):
    model_config = ConfigDict(frozen=True)

    site_id: str
    expression: str
    groups: int = Field(ge=0)
    genomes: tuple[str, ...] = Field(min_length=1)
    outside: int = Field(ge=1)

    @computed
    def length(self) -> int:
        return len(self.expression)


def _refuse(detail: str) -> ValidationError:
    return ValidationError(
        title="The clade-only expression takes clades of the site's taxonomy",
        detail=detail,
    )


def _genomes(tree: PhyleticTree, argument: str, codes: Sequence[str]) -> frozenset[str]:
    if not codes:
        msg = f"{argument} names no code."
        raise _refuse(msg)
    unknown = sorted(set(codes) - tree.codes())
    if unknown:
        msg = f"{argument} names codes the site's taxonomy does not hold: {unknown}."
        raise _refuse(msg)
    held = frozenset(tree.genomes_under(codes))
    if not held:
        msg = f"{argument} {list(codes)} holds no genome."
        raise _refuse(msg)
    return held


def _cover(
    tree: PhyleticTree, nodes: Sequence[PhyleticNode], wanted: frozenset[str]
) -> list[str]:
    codes: list[str] = []
    for node in nodes:
        held = tree.genomes_under([node.code])
        if held and held <= wanted:
            codes.append(node.code)
        elif held & wanted:
            codes.extend(_cover(tree, node.children, wanted))
    return codes


def _unit(tree: PhyleticTree, genomes: frozenset[str], count: str) -> str:
    return f"{'+'.join(_cover(tree, tree.roots, genomes))}{count}"


async def clade_only_expression(
    site_id: str, clade: Sequence[str], within: Sequence[str] | None
) -> CladeOnlyExpression:
    tree = await site_taxonomy(site_id)
    inside = _genomes(tree, "clade", clade)
    scope = inside if within is None else _genomes(tree, "within", within)
    if not inside <= scope:
        msg = (
            f"within does not hold {len(inside - scope)} genomes of clade. within "
            "is a clade that holds every genome of clade; for a clade M whose "
            "genomes must hold no protein, write L>=1T AND M=0T."
        )
        raise _refuse(msg)
    every = tree.genomes_under([root.code for root in tree.roots])
    outside = frozenset(every) - scope
    if not outside:
        msg = "It covers every genome of the site, so no genome lies outside it."
        raise _refuse(msg)
    expression = f"{_unit(tree, inside, '>=1T')} AND {_unit(tree, outside, '=0T')}"
    groups = await GroupCountReports(site_id).groups(expression)
    return CladeOnlyExpression(
        site_id=site_id,
        expression=expression,
        groups=groups,
        genomes=tuple(sorted(inside)),
        outside=len(outside),
    )

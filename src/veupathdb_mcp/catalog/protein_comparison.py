from __future__ import annotations

from pydantic import ConfigDict, Field
from veupathdb.domain.parameters import PhyleticTree
from veupathdb.errors import ValidationError
from veupathdb.model import CamelModel

from veupathdb_mcp.catalog.group_counts import GroupCountReports, site_taxonomy
from veupathdb_mcp.computed import computed

FIRST_PROBE = 128
LAST_PROBE = FIRST_PROBE * 2**3
MAX_COUNT_REPORTS = 15


class ProteinCountLadder(CamelModel):
    model_config = ConfigDict(frozen=True)

    more: str
    fewer: str
    expression: str
    groups: int = Field(ge=0)

    @computed
    def length(self) -> int:
        return len(self.expression)


class ProteinCountComparison(CamelModel):
    model_config = ConfigDict(frozen=True)

    site_id: str
    k: int = Field(ge=0)
    count_reports: int = Field(ge=1, le=MAX_COUNT_REPORTS)
    ladders: tuple[ProteinCountLadder, ...] = Field(min_length=1, max_length=2)


def _refuse(detail: str) -> ValidationError:
    return ValidationError(
        title="The protein count comparison takes two single genomes", detail=detail
    )


def _one_genome(tree: PhyleticTree, argument: str, code: str) -> None:
    if tree.genomes_under([code]) != {code}:
        msg = (
            f"{argument} {code!r} is not one genome of the site's taxonomy; give a "
            "code that lookup_phyletic_codes lists with leaf=true."
        )
        raise _refuse(msg)


async def _two_genomes(site_id: str, genome_a: str, genome_b: str) -> None:
    tree = await site_taxonomy(site_id)
    _one_genome(tree, "genome_a", genome_a)
    _one_genome(tree, "genome_b", genome_b)
    if genome_a == genome_b:
        msg = f"genome_a and genome_b name the same genome, {genome_a!r}."
        raise _refuse(msg)


async def _largest_count(reports: GroupCountReports, genome: str) -> int:
    held, empty = 0, FIRST_PROBE
    while await reports.groups(f"{genome}>={empty}") > 0:
        if empty == LAST_PROBE:
            msg = (
                f"{genome} holds {LAST_PROBE} or more proteins in one group, and a "
                "ladder that long does not finish within the call budget."
            )
            raise _refuse(msg)
        held, empty = empty, empty * 2
    while empty - held > 1:
        middle = (held + empty) // 2
        if await reports.groups(f"{genome}>={middle}") > 0:
            held = middle
        else:
            empty = middle
    return held


async def _ladder(
    reports: GroupCountReports, more: str, fewer: str, top: int
) -> ProteinCountLadder:
    expression = " OR ".join(
        f"{fewer}={count} AND {more}>={count + 1}" for count in range(top + 1)
    )
    return ProteinCountLadder(
        more=more,
        fewer=fewer,
        expression=expression,
        groups=await reports.groups(expression),
    )


async def compare_protein_counts(
    site_id: str, genome_a: str, genome_b: str, *, reverse: bool
) -> ProteinCountComparison:
    await _two_genomes(site_id, genome_a, genome_b)
    reports = GroupCountReports(site_id)
    k = await _largest_count(reports, genome_b)
    ladders = [await _ladder(reports, genome_a, genome_b, k)]
    if reverse:
        ladders.append(await _ladder(reports, genome_b, genome_a, max(k - 1, 0)))
    return ProteinCountComparison(
        site_id=site_id, k=k, count_reports=reports.sent, ladders=tuple(ladders)
    )

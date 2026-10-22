"""What the fusion check reads from a site: the gene and its ortholog group, and for a
LONG gene its reference, the genes beside the reference and their proteins."""

from __future__ import annotations

from typing import Self

from pydantic import BaseModel, ConfigDict, model_validator
from veupathdb.errors import DataParsingError

from veupathdb_mcp.audit.fusion import beside, copies_beside
from veupathdb_mcp.audit.gene_ids import id_pairs
from veupathdb_mcp.audit.genes import (
    GeneRow,
    GroupMember,
    genes_of_genome,
    orthologs_of,
    proteins_of,
)
from veupathdb_mcp.audit.lengths import NotChecked, call_length
from veupathdb_mcp.audit.served import (
    LengthScreen,
    length_screen,
    located,
    read_proteins,
)
from veupathdb_mcp.tool_errors import ToolErrorPayload


class FusionReads(BaseModel):
    model_config = ConfigDict(frozen=True)

    member: GeneRow
    member_protein: str
    reference_protein: str
    neighbours: list[GeneRow]
    neighbour_proteins: dict[str, str]


class FusionInputs(BaseModel):
    model_config = ConfigDict(frozen=True)

    screen: LengthScreen
    reads: FusionReads | None

    @model_validator(mode="after")
    def _read_when_long(self) -> Self:
        if (self.reads is not None) != (self.screen.length_class == "LONG"):
            msg = (
                f"a {self.screen.length_class} gene reads its reference's "
                "neighbours only when its class is LONG"
            )
            raise ValueError(msg)
        return self


async def _beside_reference(
    site_id: str, member: GeneRow, placed: GroupMember
) -> FusionReads | ToolErrorPayload:
    match await read_proteins(site_id, [member.gene, placed.gene]):
        case ToolErrorPayload() as refusal:
            return refusal
        case proteins:
            pass
    genome = await genes_of_genome(site_id, placed.organism)
    reference = next((row for row in genome if row.gene == placed.gene), None)
    if reference is None:
        msg = f"the genome of {placed.organism} on {site_id} lists no {placed.gene}"
        raise DataParsingError(msg)
    neighbours = beside(reference, genome)
    return FusionReads(
        member=member,
        member_protein=proteins[member.gene],
        reference_protein=proteins[placed.gene],
        neighbours=neighbours,
        neighbour_proteins=await proteins_of(site_id, [r.gene for r in neighbours]),
    )


async def read_fusion(site_id: str, gene: str) -> FusionInputs | ToolErrorPayload:
    match await located(site_id, [gene]):
        case ToolErrorPayload() as refusal:
            return refusal
        case rows:
            member = rows[gene]
    call = call_length([member], (await orthologs_of(site_id, member.gene)).members)
    screen = length_screen([member], call, id_pairs([gene], rows))
    match call:
        case NotChecked(length_class="LONG", reference=GroupMember() as reference):
            pass
        case _:
            return FusionInputs(screen=screen, reads=None)
    match await _beside_reference(site_id, member, reference):
        case ToolErrorPayload() as refusal:
            return refusal
        case FusionReads() as reads:
            return FusionInputs(screen=screen, reads=reads)


async def partner_copies(site_id: str, member: GeneRow, group: str) -> list[str]:
    genome = await genes_of_genome(site_id, member.organism)
    return copies_beside(member, genome, group)

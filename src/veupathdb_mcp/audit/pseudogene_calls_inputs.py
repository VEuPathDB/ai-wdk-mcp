"""The two genome gene reports a genome's pseudogene calls are paired from."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from veupathdb_mcp.audit.genes import GeneRow, genes_of_genome


class PseudogeneGenomes(BaseModel):
    model_config = ConfigDict(frozen=True)

    genome: list[GeneRow]
    reference: list[GeneRow]


async def pseudogene_genomes(
    site_id: str, organism: str, reference_organism: str
) -> PseudogeneGenomes:
    return PseudogeneGenomes(
        genome=await genes_of_genome(site_id, organism),
        reference=await genes_of_genome(site_id, reference_organism),
    )

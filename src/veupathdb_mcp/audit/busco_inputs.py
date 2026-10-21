"""The organism report the genome-priority check reads from a site."""

from __future__ import annotations

from veupathdb_mcp.audit.busco import BUSCO_ATTRIBUTES, GenomePriority, ranked_genomes
from veupathdb_mcp.audit.genes import organism_report


async def genome_priorities(site_id: str) -> list[GenomePriority]:
    return ranked_genomes((await organism_report(site_id, BUSCO_ATTRIBUTES)).records)

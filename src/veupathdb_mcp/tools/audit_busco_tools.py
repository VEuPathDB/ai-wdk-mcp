"""The served genome-priority check, read from the site the call names."""

from __future__ import annotations

from veupathdb_mcp.audit.busco import GenomePriorities
from veupathdb_mcp.audit.busco_inputs import genome_priorities
from veupathdb_mcp.tools.audit_tools import read_inputs


async def audit_genome_priority(site_id: str) -> GenomePriorities:
    """Rank a site's genomes by the conserved genes their annotation misses.

    Each organism record of the site serves two BUSCO scores: the share of
    conserved single-copy genes found complete in its annotated proteins
    (protein) and in its genome sequence (genome). gap is genome minus
    protein completeness, in percentage points: conserved genes the genome
    holds but the annotation lacks. genomes lists them largest gap first, so the
    gene-level checks run where the annotation misses most. An organism
    without both scores is left out. The scores are genome-level only: the
    sites do not serve which genes BUSCO found missing.

    Args:
        site_id: VEuPathDB site, for example 'plasmodb'.
    """
    genomes = await read_inputs(site_id, genome_priorities(site_id))
    return GenomePriorities(site_id=site_id, genomes=genomes)

"""The served organelle check: a gene cut by the two ends of a circular genome
stored as a line."""

from __future__ import annotations

from fastmcp.exceptions import ToolError

from veupathdb_mcp.audit.organelle import check_circular_join
from veupathdb_mcp.audit.organelle_inputs import OrganelleGeneAudit, organelle_inputs
from veupathdb_mcp.tools.audit_tools import read_inputs, run_in_a_slot


async def audit_organelle_gene(
    site_id: str,
    organism: str,
    sequence_id: str,
    reference_gene: str,
) -> OrganelleGeneAudit:
    """Check whether an organelle gene is cut in two by the ends of its contig.

    A mitochondrial or plastid genome is a circle that the site stores as one
    line, so a gene across the join lies in two pieces at the contig ends.
    The whole contig is translated in six frames with the code the reference
    gene's own coding sequence reads: as stored, and as a circle turned by
    half its length. When the last and first 20 or more bases of the
    contig agree at 99% of positions and do not repeat a unit of 6 bases or
    fewer, the longest such overlap is joined once (overlapBases,
    overlapMismatches); a direct repeat at both ends reads as an overlap too.
    A reference that codes more than half the circle is refused.
    SPLIT_AT_JOIN means only the circle has one open frame that holds 95% of
    the reference protein's residues; INTACT_ON_THE_LINE means the contig as
    stored has it; NOT_FOUND means neither has it, which a frameshift in the
    assembly or a reference of another species also gives. bestLinear and
    bestCircular are the most reference residues one open frame holds, in
    runs of 4 or more.
    geneIds pairs each id given with the site's own gene id it names (the
    same id, an alias, a transcript id, or the one gene whose own id is the
    id with a ":" qualifier added); every other gene field holds that id.

    Args:
        site_id: VEuPathDB site, for example 'plasmodb'.
        organism: The organism's full name, for example 'Plasmodium falciparum NF54'.
        sequence_id: The organelle contig, for example 'CM019798.1'.
        reference_gene: The intact gene of a strain of the same species (95% identical), for example 'PF3D7_MIT02300'.
    """
    inputs = await read_inputs(
        site_id, organelle_inputs(site_id, organism, sequence_id, reference_gene)
    )
    try:
        check = await run_in_a_slot(
            check_circular_join, inputs.contig, inputs.reference_protein, inputs.code
        )
    except ValueError as exc:
        msg = f"{reference_gene} against {sequence_id}: {exc}"
        raise ToolError(msg) from exc
    return OrganelleGeneAudit.model_validate(
        {
            **check.model_dump(),
            "gene_ids": inputs.gene_ids,
            "organism": organism,
            "sequence_id": sequence_id,
            "reference_gene": inputs.gene_ids[0].resolved,
            "contig_length": len(inputs.contig),
            "code": inputs.code,
            "code_inferred": inputs.code_inferred,
        }
    )

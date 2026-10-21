"""The served check of a long protein's extra residues against the genes beside its
reference."""

from __future__ import annotations

from veupathdb_mcp.audit.fusion import (
    FusionAudit,
    FusionCheck,
    GeneFusionAudit,
    check_fusion,
)
from veupathdb_mcp.audit.fusion_inputs import FusionReads, partner_copies, read_fusion
from veupathdb_mcp.audit.lengths import is_orthology_group
from veupathdb_mcp.tools.audit_tools import read_inputs, run_in_a_slot


async def _fusion(site_id: str, reads: FusionReads, check: FusionCheck) -> FusionAudit:
    partner = next((row for row in reads.neighbours if row.gene == check.partner), None)
    copies = (
        await read_inputs(
            site_id, partner_copies(site_id, reads.member, partner.ortholog_group)
        )
        if partner is not None and is_orthology_group(partner.ortholog_group)
        else None
    )
    return FusionAudit(
        extra=check.extra,
        partner=check.partner,
        closest_neighbour=check.closest_neighbour,
        neighbour_windows=check.neighbour_windows,
        neighbours=[row.gene for row in reads.neighbours],
        product=reads.member.product,
        partner_group=partner.ortholog_group if partner else None,
        partner_product=partner.product if partner else None,
        partner_copies=copies,
    )


async def audit_gene_fusion(site_id: str, gene: str) -> GeneFusionAudit:
    """Check whether a long protein's extra residues match a gene beside its reference.

    The gene is classed as in audit_gene_length; only a LONG gene is checked,
    and every other class answers fusion null with no protein read. For a
    LONG gene, extra lists the residue spans of its protein (1-based,
    inclusive) whose 20-residue windows (step 10) the protein of the closest
    single-copy ortholog (referenceGene) holds at identity under 0.35, in
    runs of 2 or more windows, as in audit_strain_model. Windows the
    reference protein holds at identity 0.35 or more, low-complexity windows
    and windows repeated elsewhere in the protein are not extra, so a tandem
    duplicate or a repeat expansion answers NO_EXTRA. Each extra window is
    then matched against the proteins of the genes beside the reference
    (neighbours: up to 3 on each side on its sequence, in position order);
    a window counts for the neighbour that holds it at the highest identity,
    when that is 0.5 or more, and neighbourWindows counts the windows of the
    neighbour that holds the most. EXTRA_MATCHES_NEIGHBOUR means the model's
    extra residues match the protein of the neighbour partner names
    (neighbourWindows of extraWindows windows): it holds at least 3 extra
    windows and at least 40% of them; partnerGroup and partnerProduct are
    that neighbour's. The answer states the protein match only and says
    nothing of how the model was built. product is the checked gene's own,
    and a product that names both proteins can mark a fusion the curators
    chose. EXTRA_UNEXPLAINED means no neighbour reaches that bar, and
    closestNeighbour names the one that holds the most windows, null when
    none holds one; it is not a fusion partner. NO_EXTRA means the protein
    holds no extra window. For a partner in an orthology group (OG, not
    OGR), partnerCopies lists the genes within 3 of the checked gene on its
    own sequence that are in the partner's group, a separate model of that
    neighbour beside the checked gene; it is null otherwise.
    geneIds pairs each id given with the site's own gene id it names (the
    same id, an alias, a transcript id, or the one gene whose own id is the
    id with a ":" qualifier added); every other gene field holds that id.

    Args:
        site_id: VEuPathDB site, for example 'plasmodb'.
        gene: The gene whose model is checked.
    """
    inputs = await read_inputs(site_id, read_fusion(site_id, gene))
    reads = inputs.reads
    fusion = None
    if reads is not None:
        check = await run_in_a_slot(
            check_fusion,
            reads.member_protein,
            reads.reference_protein,
            reads.neighbour_proteins,
        )
        fusion = await _fusion(site_id, reads, check)
    return GeneFusionAudit.model_validate(
        {**inputs.screen.model_dump(), "fusion": fusion}
    )

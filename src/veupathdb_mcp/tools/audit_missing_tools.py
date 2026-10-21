"""The served check for a gene one genome's annotation lacks."""

from __future__ import annotations

from veupathdb_mcp.audit.missing import (
    AnnotatedMember,
    MissingGeneAudit,
    OverlappingGene,
    missing_verdict,
    overlapping,
    scan_for_protein,
)
from veupathdb_mcp.audit.missing_inputs import missing_inputs
from veupathdb_mcp.tools.audit_tools import read_inputs, run_in_a_slot


async def audit_missing_gene(
    site_id: str,
    example_gene: str,
    absent_organism: str,
) -> MissingGeneAudit:
    """Check whether a genome holds a gene its annotation lacks.

    Up to 6 genes on each side of the example gene, on its contig, are read
    outward until each side has a neighbour whose OG ortholog group (not a
    residual OGR group, not an N/A label) has exactly one gene in the absent
    organism; those two genes are the anchors, which must be two genes on one
    contig within 60 kb. The example protein must have 40 residues or more.
    The DNA between the anchors, padded by 3 kb, is translated in six frames
    with the genetic code inferred from the example gene's own CDS and
    protein (the standard code, codeInferred false, when none explains it),
    and searched for 20-residue windows of the example protein at identity
    0.5 or more. IN_DNA_UNANNOTATED means 60% or more of the windows are
    found and no gene model overlaps their span: the DNA holds the protein's
    sequence, not necessarily one intact reading frame. stops lists the stop
    codons inside the stretch that the found windows cover in the frame that
    holds the most of them, as residue positions of the example protein;
    intactFrame is true only when every found window lies in one frame and
    that frame has no stop over the whole protein. IN_DNA_OTHER_MODEL means a model overlaps the span
    (overlapping names it, and pseudo marks a pseudogene, which a gene's
    Orthologs table does not list). GAP means fewer are found and the DNA
    holds more than 100 Ns; PARTIAL means 35% or more are found; NOT_IN_DNA
    means fewer. NO_SYNTENY means no anchor pair was found. ANNOTATED_IN_GENOME
    means the absent organism annotates genes of the example's OG ortholog
    group, wherever they sit, the syntenic locus included (annotatedMembers
    names each with its sequence and start), so its annotation does not
    lack the gene and no DNA is read. annotatedMembers
    is empty when the absent organism holds no member of the group, and null
    when the example's group is not an OG group, so membership was not
    checked. NO_SYNTENY and ANNOTATED_IN_GENOME read no genome: anchors,
    located, overlapping, stops and code are null and codeInferred is false.
    openFrame
    is the stop-free stretch over the span, read to its stop codon or the
    window end, that shares the most residues with the example protein.
    geneIds pairs each id given with the site's own gene id it names (the
    same id, an alias, a transcript id, or the one gene whose own id is the
    id with a ":" qualifier added); every other gene field holds that id.

    Args:
        site_id: VEuPathDB site, for example 'toxodb'.
        example_gene: A gene of a genome that has it.
        absent_organism: The full name of the organism whose annotation
            lacks it, for example 'Toxoplasma gondii GT1'.
    """
    inputs = await read_inputs(
        site_id, missing_inputs(site_id, example_gene, absent_organism)
    )
    dna = inputs.dna
    [named] = inputs.gene_ids
    members = (
        None
        if inputs.annotated_members is None
        else [
            AnnotatedMember.model_validate(r.model_dump())
            for r in inputs.annotated_members
        ]
    )
    if dna is None:
        return MissingGeneAudit(
            verdict="ANNOTATED_IN_GENOME" if members else "NO_SYNTENY",
            gene_ids=inputs.gene_ids,
            example_gene=named.resolved,
            absent_organism=absent_organism,
            example_length=len(inputs.protein),
            annotated_members=members,
            anchors=None,
            located=None,
            overlapping=None,
            open_frame=None,
            stops=None,
            intact_frame=None,
            code=None,
            code_inferred=False,
        )
    scan = await run_in_a_slot(
        scan_for_protein, inputs.protein, dna.sequence, dna.start, dna.code
    )
    over = overlapping(dna.genes, scan.located.span)
    return MissingGeneAudit(
        verdict=missing_verdict(scan.located, over),
        gene_ids=inputs.gene_ids,
        example_gene=named.resolved,
        absent_organism=absent_organism,
        example_length=len(inputs.protein),
        annotated_members=members,
        anchors=dna.anchors,
        located=scan.located,
        overlapping=[OverlappingGene.model_validate(r.model_dump()) for r in over],
        open_frame=scan.open_frame,
        stops=scan.stops,
        intact_frame=scan.intact_frame,
        code=dna.code,
        code_inferred=dna.code_inferred,
    )

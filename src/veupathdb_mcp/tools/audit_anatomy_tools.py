"""The served pseudogene anatomy, read from the site the call names."""

from __future__ import annotations

from veupathdb_mcp.audit.anatomy import Anatomy, pseudogene_anatomy
from veupathdb_mcp.audit.anatomy_inputs import anatomy_inputs
from veupathdb_mcp.audit.codes import GeneticCode
from veupathdb_mcp.audit.pseudogene import check_pseudogene_call
from veupathdb_mcp.tools.audit_tools import read_inputs, run_in_a_slot


async def audit_pseudogene_anatomy(
    site_id: str,
    strain_gene: str,
    reference_gene: str,
) -> Anatomy:
    """State where a pseudogene's model breaks and what the genome holds there.

    The strain gene must be one the site flags as a pseudogene (is_pseudo
    Yes); any other gene is refused. The segments are the Exon rows of the
    strain gene's transcript with the largest summed Exon length. Each junction
    between two segments gives the last base of one (after) and the first
    base of the next (before), the bases between them (gap) and the gap
    modulo 3 (gapMod3), the longest single-base run of the genome with a base
    within 5 positions of the gap's first base (after + 1) or last base
    (before - 1), inside or outside the gap (runBase, runLength), and the Ns
    within 100 positions of those two bases (nsWithin100). toContigStart and
    toContigEnd are the bases from the first and last segment to the contig
    ends; nsInGene counts the Ns between them. Positions and runBase are on
    the genome's plus strand, and segments and junctions are in ascending
    position. referenceSegments is the number of Exon rows of the reference
    gene's transcript with the largest summed Exon length, and dnaCheck is
    the pseudogene check of the strain's genome window against the coding
    sequence of the reference's transcript with the longest CDS; for a
    reference with several transcripts the two can describe different
    transcripts. dnaCheck translates with the standard genetic code; it does
    not infer the gene's code. It states facts only.
    Reads: the record of each id; both gene models (one gene record read
    each); two JBrowse genome windows and the strain contig's length from
    the organism's FASTA index.
    geneIds pairs each id given with the site's own gene id it names (the
    same id, an alias or a previous id its gene record read resolves, a
    transcript id the site's text search names, or the one gene whose own id
    is the id with a ":" qualifier added); every other gene field holds that
    id. Each id given costs one gene record read; an id no record names adds
    one text search and one record read of the gene it names. Resolving ids
    uploads no gene list, and a refusal names an id that names several genes.

    Args:
        site_id: VEuPathDB site, for example 'plasmodb'.
        strain_gene: The gene the strain annotates as a pseudogene.
        reference_gene: The coding gene of the reference strain it is read against.
    """
    inputs = await read_inputs(
        site_id, anatomy_inputs(site_id, strain_gene, reference_gene)
    )
    model = await run_in_a_slot(
        pseudogene_anatomy,
        inputs.segments,
        inputs.window,
        inputs.window_start,
        inputs.contig_length,
    )
    dna_check = await run_in_a_slot(
        check_pseudogene_call,
        inputs.pseudogene.reference,
        inputs.pseudogene.strain_coding_dna,
        GeneticCode.STANDARD,
    )
    strain, reference = inputs.pseudogene.gene_ids
    return Anatomy.model_validate(
        {
            **model.model_dump(),
            "gene_ids": inputs.pseudogene.gene_ids,
            "strain_gene": strain.resolved,
            "reference_gene": reference.resolved,
            "reference_segments": inputs.reference_segments,
            "dna_check": dna_check,
        }
    )

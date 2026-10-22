"""The served check of a strain's gene model against its species reference."""

from __future__ import annotations

from veupathdb_mcp.audit.length import LengthCheck, check_length
from veupathdb_mcp.audit.served import LengthDna
from veupathdb_mcp.audit.strain import (
    NotRead,
    Run,
    StrainModelAudit,
    judged_side,
    missing_runs,
    strain_relatives,
)
from veupathdb_mcp.audit.strain_inputs import (
    StrainInputs,
    paralogs_in_window,
    strain_dna,
    strain_inputs,
)
from veupathdb_mcp.tools.audit_tools import read_inputs, run_in_a_slot


def _not_read(
    inputs: StrainInputs, lost: list[Run], paralogs: list[str]
) -> NotRead | None:
    if inputs.group is None:
        return "UNQUALIFIED"
    if not lost:
        return "NO_LOST_RUN"
    if paralogs:
        return "PARALOG_IN_WINDOW"
    return None


async def _genome_check(
    site_id: str, inputs: StrainInputs
) -> tuple[LengthCheck, LengthDna]:
    dna = await read_inputs(site_id, strain_dna(site_id, inputs))
    check = await run_in_a_slot(
        check_length, dna.reference_protein, dna.model_proteins, dna.window, dna.code
    )
    return check, dna


async def audit_strain_model(
    site_id: str,
    strain_gene: str,
    reference_gene: str,
) -> StrainModelAudit:
    """Check a strain's gene model against its species reference, and which is wrong.

    Both genes must be one species, two organisms and one ortholog group.
    lost lists the residue spans of the reference protein (1-based,
    inclusive) whose 20-residue windows (step 10) the strain protein holds
    at identity under 0.35, in runs of 2 or more windows; extra lists the
    same spans of the strain protein against the reference. Windows of low
    complexity (one residue in 40% or more, or 6 or fewer distinct
    residues) and windows repeated elsewhere in the same protein are not
    counted. When the strain lost a run, its genome region is read for the
    reference protein as in audit_gene_length: GENOME_ENCODES means the
    strain's genome holds the lost segment on the gene's strand. notRead
    says why no genome was read: NO_LOST_RUN; UNQUALIFIED, a residual (OGR)
    group, which is not orthology; or PARALOG_IN_WINDOW, another member of
    the group in the strain's organism, coding or not, on the same sequence
    within the read window (nearbyParalogs names them; a copy the group
    does not list is not seen). relatives lists,
    for each organism of the other species of the reference's genus (other
    genera when the genus has fewer than two), its longest member, leaving
    out the organisms of both genes, and relatives.median is their median;
    missing says why there are none:
    RESIDUAL_GROUP; PARALOGS when the group's copiesPerOrganism is not 1;
    or FEWER_THAN_TWO. side is judged only
    when the DNA verdict is GENOME_ENCODES, and is NOT_JUDGED otherwise:
    STRAIN_SHORT means the reference is within 10% of relatives.median and
    the shorter strain is not, so the strain model misses what its genome
    encodes; REFERENCE_LONG means the strain is within 10% and the longer
    reference is not, so the strain's genome encodes a segment the
    relatives lack and the reference model holds it, as a model that
    starts too early does; UNCLEAR is every other case, a strain longer
    than its reference among them; NO_RELATIVES means relatives is empty.
    Reads: the record of each id; both proteins (one gene record read of
    the transcripts and one transcript record read of the longest coding
    one, each); the reference's Orthologs table (one read whatever the
    group's size). A lost run adds the strain's gene model and one genome
    window; when the group has another member in the strain's organism, it
    first adds the strain's organism (one gene record read), that organism's
    JBrowse track list and the tabix index of its annotated transcripts
    track (once per organism and process), and up to ANNOTATION_MAX_GROUPS
    (4) range reads over the window, one per chunk group, which place the
    members (more groups is a refusal, and a sequence the track does not
    index places none). Beyond the reads made once per organism, a call
    makes at most 5 store reads: the genome window and the 4 range reads.
    geneIds pairs each id given with the site's own gene id it names (the
    same id, an alias or a previous id its gene record read resolves, a
    transcript id the site's text search names, or the one gene whose own id
    is the id with a ":" qualifier added); every other gene field holds that
    id. Each id given costs one gene record read; an id no record names adds
    one text search and one record read of the gene it names. Resolving ids
    uploads no gene list, and a refusal names an id that names several genes.

    Args:
        site_id: VEuPathDB site, for example 'plasmodb'.
        strain_gene: The strain's gene whose model is checked.
        reference_gene: The gene of the species reference it is read against.
    """
    inputs = await read_inputs(
        site_id, strain_inputs(site_id, strain_gene, reference_gene)
    )
    lost = await run_in_a_slot(
        missing_runs, inputs.reference_protein, inputs.strain_protein
    )
    extra = await run_in_a_slot(
        missing_runs, inputs.strain_protein, inputs.reference_protein
    )
    paralogs = (
        await read_inputs(site_id, paralogs_in_window(site_id, inputs)) if lost else []
    )
    not_read = _not_read(inputs, lost, paralogs)
    check, dna = (
        (LengthCheck.not_checked(), None)
        if not_read
        else await _genome_check(site_id, inputs)
    )
    relatives = strain_relatives(inputs.reference, inputs.strain, inputs.group)
    reference_length = len(inputs.reference_protein)
    strain_length = len(inputs.strain_protein)
    return StrainModelAudit(
        gene_ids=inputs.gene_ids,
        strain_gene=inputs.strain.gene,
        reference_gene=inputs.reference.gene,
        strain_length=strain_length,
        reference_length=reference_length,
        lost=lost,
        extra=extra,
        dna=check,
        not_read=not_read,
        nearby_paralogs=paralogs if not_read == "PARALOG_IN_WINDOW" else [],
        side=judged_side(
            check.verdict, reference_length, strain_length, relatives.median
        ),
        relatives=relatives,
        code=dna.code if dna else None,
        code_inferred=dna.code_inferred if dna else False,
    )

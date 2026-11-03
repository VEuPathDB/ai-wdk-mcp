"""The served gene-model checks, read from the site the call names."""

from __future__ import annotations

import asyncio
import weakref
from collections.abc import Awaitable, Callable
from enum import StrEnum

import httpx
from fastmcp.exceptions import ToolError
from veupathdb.errors import VEuPathDBError

from veupathdb_mcp.audit import (
    GeneLengthAudit,
    GeneticCode,
    LengthCheck,
    LengthDna,
    ModelReads,
    ModelRecord,
    PseudogeneCallAudit,
    ReadModels,
    SelenoproteinEndAudit,
    check_length,
    check_pseudogene_call,
    check_sec_stop,
    compared_to_reference,
    length_inputs,
    pseudogene_inputs,
    selenoprotein_inputs,
)
from veupathdb_mcp.audit.track_reads import UNREADABLE_ANSWER, upstream_answer
from veupathdb_mcp.tool_errors import ToolErrorPayload
from veupathdb_mcp.tools.refusals import payload_or_error

_CODE = GeneticCode.STANDARD
_CHECKS_AT_ONCE = 2
_SLOTS: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore] = (
    weakref.WeakKeyDictionary()
)


def audit_slots() -> asyncio.Semaphore:
    return _SLOTS.setdefault(
        asyncio.get_running_loop(), asyncio.Semaphore(_CHECKS_AT_ONCE)
    )


async def run_in_a_slot[**P, T](
    check: Callable[P, T], *args: P.args, **kwargs: P.kwargs
) -> T:
    slots = audit_slots()
    await slots.acquire()
    work = asyncio.ensure_future(asyncio.to_thread(check, *args, **kwargs))
    work.add_done_callback(lambda _: slots.release())
    return await asyncio.shield(work)


def site_failure(
    site_id: str, exc: VEuPathDBError[StrEnum] | httpx.HTTPError, reads: str
) -> str:
    match (upstream_answer(exc), exc):
        case (int() as status, _):
            return f"{site_id} answered {status} to the {reads}"
        case ("silent", _):
            return f"{site_id} did not answer the {reads}"
        case ("unreadable", _):
            return UNREADABLE_ANSWER
        case (_, VEuPathDBError() as refusal):
            return refusal.detail or refusal.title
        case _:
            return f"{site_id} did not answer the {reads}"


async def read_inputs[T](site_id: str, inputs: Awaitable[T | ToolErrorPayload]) -> T:
    try:
        return payload_or_error(await inputs)
    except (VEuPathDBError, httpx.HTTPError) as exc:
        raise ToolError(site_failure(site_id, exc, "audit reads")) from exc


async def audit_pseudogene_call(
    site_id: str,
    strain_gene: str,
    reference_gene: str,
) -> PseudogeneCallAudit:
    """Check whether a strain gene called a pseudogene is an intact coding sequence.

    The strain gene must be one the site flags as a pseudogene (is_pseudo
    Yes); any other gene is refused. The strain's genome around the gene is
    aligned to the reference gene's coding sequence and translated. INTACT
    means one open frame from start to stop; the other verdicts name what
    breaks it. prematureStops lists the residue positions of the first 20
    in-frame stops before the last codon, and prematureStopsTruncated is
    true when the frame holds more. The check translates with the standard genetic code; it does
    not infer the gene's code, so a gene of a clade that reads TGA or CTG
    otherwise can read a stop or a substitution here. referenceModel gives
    the reference transcript's exon and CDS spans (genome coordinates, 1-based, inclusive, ascending), its seqid and strand.
    It is null when the reference's model rows give no Exon row or lie on
    more than one sequence or strand, and evidenceUnread gives why.
    Reads: the record of each id, then the reference's gene model and the
    strain's organism (one gene record read each) and two JBrowse genome
    windows (the reference span, and the strain span with 3,000 bases on
    each side).
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
        site_id, pseudogene_inputs(site_id, strain_gene, reference_gene)
    )
    check = await run_in_a_slot(
        check_pseudogene_call, inputs.reference, inputs.strain_coding_dna, _CODE
    )
    strain, reference = inputs.gene_ids
    return PseudogeneCallAudit.model_validate(
        {
            **check.model_dump(),
            "gene_ids": inputs.gene_ids,
            "strain_gene": strain.resolved,
            "reference_gene": reference.resolved,
            "reference_model": inputs.reference_models.models[0],
            "evidence_unread": inputs.reference_models.evidence_unread,
        }
    )


async def audit_selenoprotein_end(
    site_id: str,
    gene: str,
    reference_gene: str,
) -> SelenoproteinEndAudit:
    """Check whether a gene model ends at the TGA that encodes its selenocysteine.

    The model protein is aligned to the reference protein: secAligned is
    true when the model's last residue, read along the last stretch of
    identical residues that ends at most 3 residues before it, falls on the
    residue just before the reference's first selenocysteine (U). tailIdentity is the share of
    the reference tail after that U (to its stop) that the genome after the
    model end encodes, residue by residue, up to the first stop the genome
    reads there. STOPS_AT_SEC means secAligned is true, the model stops at a
    TGA and tailIdentity is 0.8 or more, so the tail may differ across
    species. NOT_AT_SEC means the model end was found in the genome but not
    so; MODEL_NOT_FOUND means it was not found. CONTAINS_SEC means the model
    already holds the selenocysteine, and then nothing is aligned or compared.
    The check translates with the standard genetic code; it does not infer
    the gene's code. models gives the gene's, then the reference's, longest
    coding transcript: its exon and CDS spans (genome coordinates, 1-based, inclusive, ascending), its seqid and strand.
    A model is null when its rows give no CDS row, no Exon row or more than
    one sequence or strand; evidenceUnread gives one reason for each null.
    Reads: the record of each id; each protein as one gene record read of
    its transcripts and one transcript record read of the longest coding
    one; the gene's organism and gene model (one gene record read); the
    reference's gene model (one gene record read); one genome window.
    geneIds pairs each id given with the site's own gene id it names (the
    same id, an alias or a previous id its gene record read resolves, a
    transcript id the site's text search names, or the one gene whose own id
    is the id with a ":" qualifier added); every other gene field holds that
    id. Each id given costs one gene record read; an id no record names adds
    one text search and one record read of the gene it names. Resolving ids
    uploads no gene list, and a refusal names an id that names several genes.

    Args:
        site_id: VEuPathDB site, for example 'toxodb'.
        gene: The gene whose model is checked.
        reference_gene: A gene whose protein holds the selenocysteine.
    """
    inputs = await read_inputs(
        site_id, selenoprotein_inputs(site_id, gene, reference_gene)
    )
    check = await run_in_a_slot(
        check_sec_stop,
        inputs.model_protein,
        inputs.reference_protein,
        inputs.dna,
        inputs.strand,
        _CODE,
    )
    named, reference = inputs.gene_ids
    return SelenoproteinEndAudit.model_validate(
        {
            **check.model_dump(),
            "gene_ids": inputs.gene_ids,
            "gene": named.resolved,
            "reference_gene": reference.resolved,
            **inputs.models.model_dump(),
        }
    )


async def compared_check(
    site_id: str,
    check: LengthCheck,
    dna: LengthDna,
    record: ModelRecord | None = None,
) -> LengthCheck:
    reference = dna.strain_reference
    if reference is None or not check.lists_a_run_that_explains_a_shift:
        return check
    if record is None:
        record = await read_inputs(site_id, ModelReads(site_id).read(reference.gene))
    return await read_inputs(
        site_id,
        compared_to_reference(site_id, check, dna.window, reference, record),
    )


async def _length_audit(site_id: str, genes: list[str]) -> GeneLengthAudit:
    inputs = await read_inputs(site_id, length_inputs(site_id, genes))
    dna = inputs.dna
    if dna is None:
        check = LengthCheck.not_checked()
    else:
        check = await run_in_a_slot(
            check_length,
            dna.reference_protein,
            dna.model_proteins,
            dna.window,
            dna.code,
        )
        check = await compared_check(site_id, check, dna)
    return GeneLengthAudit.model_validate(
        {
            **check.model_dump(),
            **inputs.screen.model_dump(),
            "code": dna.code if dna else None,
            "code_inferred": dna.code_inferred if dna else False,
            **(ReadModels.of(dna.models) if dna else ReadModels()).model_dump(),
        }
    )


async def audit_gene_length(site_id: str, gene: str) -> GeneLengthAudit:
    """Check whether a protein is much shorter or longer than its orthologs, and why.

        The protein length is read against the median of the other organisms of
        its genus in its ortholog group (the group median when the genus has
        fewer than two others). SHORT is under 0.7 of it and LONG over 1.5.
        The class is UNQUALIFIED when the group has under 8 organisms, a median
        under 80 residues, an interquartile range over 0.3 of the median, more
        than one copy per organism or no single-copy member in another organism;
        when the group is residual (OGR); when a genus relative is itself under
        0.85 (for SHORT) or over 1.15 (for LONG) of the median; or when the
        gene's own organism holds another member of the group (check that pair
        with audit_gene_split). Only a SHORT gene's genome region is read, for
        the protein of the closest single-copy ortholog: GENOME_ENCODES means
        the genome holds the missing segment on the gene's strand and in the
        model's open reading frame, so the model misses it; an N in the stretch
        between the parts answers ASSEMBLY first. A part in another frame answers
        FRAMESHIFT when a run sits at a change, the shift is 1 or 2 copies of its unit
        and no splice pair sits at it; else OTHER_FRAME, whose cause is not
        shown. frameChanges states each jump between frames of the whole track under
        every verdict, whatever its size: its genome span, both frames, the shift,
        keepsFrame for a shift that is a multiple of 3, the residues of the reference
        protein, the run, the splice pair at it and whether the model goes on past it.
        unlistedChanges holds the jumps past the third, not read further. A jump with
        runExplainsShift lists first, and only it reads further. When the group
        marks one other strain of the species as its reference strain, referenceRun
        gives the same stretch in its gene, found between flanks that each occur
        once, else referenceUnread says why, and countsMatchShift says whether the
        two counts differ by the shift. variantCalls states each record of the
        site's VariantsByLocation search over it, with variantType, indelRefAllele
        and indelFrameEffect as served and the genotype, allele, depth and read
        frequency of each sample matched by name, else variantsUnread says why; it
        draws no conclusion. callsSayLittle is true over a homopolymer of 7 or more
        bases with no indel record, where the served calls hold almost no indel.
    ASSEMBLY means a gap or a contig end can explain it; ABSENT
        means the genome lacks it; NOT_SHORT means the model holds every window.
        Every other class answers NOT_CHECKED with no genome read, and then
        nsInWindow and atContigEdge are null; organisms, groupMedian,
        groupCopies and groupSpread show what the group holds. models gives the
        gene's longest coding transcript (exon and CDS spans (genome coordinates, 1-based, inclusive, ascending), its seqid and strand)
        when the genome was read, and is empty otherwise. A model is null when
        its GeneModelDump rows give no CDS row, no Exon row or more than one
        sequence or strand; evidenceUnread gives one reason for each null model.
        Reads: the record of the id; the gene record's Orthologs table (one read
        whatever the group's size; the group's protein lengths are the table's,
        and a member it gives no length counts as not coding). Only a SHORT
        gene adds the proteins of the gene and the reference (two record reads
        each), its gene model (one read) and one genome window. A FRAMESHIFT
        with a reference strain adds its gene model (one read), one genome
        window and, per change whose flanks it holds, one search read, one
        search and one record read per variant, up to 50.
        geneIds pairs each id given with the site's own gene id it names (the
        same id, an alias or a previous id its gene record read resolves, a
        transcript id the site's text search names, or the one gene whose own id
        is the id with a ":" qualifier added); every other gene field holds that
        id. Each id given costs one gene record read; an id no record names adds
        one text search and one record read of the gene it names. Resolving ids
        uploads no gene list, and a refusal names an id that names several genes.

        Args:
            site_id: VEuPathDB site, for example 'plasmodb'.
            gene: The gene whose protein length is checked.
    """
    return await _length_audit(site_id, [gene])


async def audit_gene_split(site_id: str, gene_a: str, gene_b: str) -> GeneLengthAudit:
    """Check whether two neighbouring gene models are one gene split in two.

    Both genes must be coding members of gene_a's ortholog group, and the
    only two coding members of it in their organism, on one strand of one
    sequence and at most 20,000 bases apart; three or more coding members in
    the organism make the pair UNQUALIFIED. The pair is a SPLIT when
    each protein is under 0.85 of its genus median and the two sum to 0.8
    to 1.35 of it. The genome region of a SPLIT pair is then read for the
    protein of the closest single-copy ortholog: SPLIT_CONFIRMED means each
    model holds at least 3 of its windows and the two together hold 60% of
    them; SPLIT_UNCLEAR means they do not. A pair that is not a SPLIT, or
    that the group cannot judge (UNQUALIFIED), answers NOT_CHECKED and reads
    no genome. models gives each model's longest coding transcript (exon and CDS spans (genome coordinates, 1-based, inclusive, ascending), its seqid and strand)
    when the genome was read, and is empty otherwise. A model is null when
    its GeneModelDump rows give no CDS row, no Exon row or more than one
    sequence or strand; evidenceUnread gives one reason for each null model.
    Reads: the record of each id; gene_a's Orthologs table (one read
    whatever the group's size). Only a SPLIT pair adds the proteins of both
    models and the reference (two record reads each), both gene models
    (one read each) and one genome window.
    geneIds pairs each id given with the site's own gene id it names (the
    same id, an alias or a previous id its gene record read resolves, a
    transcript id the site's text search names, or the one gene whose own id
    is the id with a ":" qualifier added); every other gene field holds that
    id. Each id given costs one gene record read; an id no record names adds
    one text search and one record read of the gene it names. Resolving ids
    uploads no gene list, and a refusal names an id that names several genes.

    Args:
        site_id: VEuPathDB site, for example 'plasmodb'.
        gene_a: One of the two models, whose ortholog group is read.
        gene_b: The neighbouring model on the same strand.
    """
    return await _length_audit(site_id, [gene_a, gene_b])

"""The served gene-model checks, read from the site the call names."""

from __future__ import annotations

import asyncio
import weakref
from collections.abc import Awaitable, Callable

import httpx
from fastmcp.exceptions import ToolError
from veupathdb.errors import VEuPathDBError

from veupathdb_mcp.audit import (
    GeneLengthAudit,
    GeneticCode,
    LengthCheck,
    PseudogeneCallAudit,
    SelenoproteinEndAudit,
    check_length,
    check_pseudogene_call,
    check_sec_stop,
    length_inputs,
    pseudogene_inputs,
    selenoprotein_inputs,
)
from veupathdb_mcp.tool_errors import ToolErrorPayload
from veupathdb_mcp.tools.refusals import payload_or_error

_CODE = GeneticCode.STANDARD
_CHECKS_AT_ONCE = 2
_SLOTS: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore] = (
    weakref.WeakKeyDictionary()
)


def _slots() -> asyncio.Semaphore:
    return _SLOTS.setdefault(
        asyncio.get_running_loop(), asyncio.Semaphore(_CHECKS_AT_ONCE)
    )


async def _in_a_slot[**P, T](
    check: Callable[P, T], *args: P.args, **kwargs: P.kwargs
) -> T:
    slots = _slots()
    await slots.acquire()
    work = asyncio.ensure_future(asyncio.to_thread(check, *args, **kwargs))
    work.add_done_callback(lambda _: slots.release())
    return await asyncio.shield(work)


async def _read[T](site_id: str, inputs: Awaitable[T | ToolErrorPayload]) -> T:
    try:
        return payload_or_error(await inputs)
    except VEuPathDBError as exc:
        raise ToolError(exc.detail or exc.title) from exc
    except httpx.HTTPError as exc:
        msg = f"{site_id} did not answer the audit reads: {type(exc).__name__} {exc}"
        raise ToolError(msg) from exc


async def audit_pseudogene_call(
    site_id: str,
    strain_gene: str,
    reference_gene: str,
) -> PseudogeneCallAudit:
    """Check whether a strain gene called a pseudogene is an intact coding sequence.

    The strain's genome around the gene is aligned to the reference gene's
    coding sequence and translated. INTACT means one open frame from start to
    stop; the other verdicts name what breaks it.

    Args:
        site_id: VEuPathDB site, for example 'plasmodb'.
        strain_gene: The gene the strain annotates as a pseudogene.
        reference_gene: The coding gene of the reference strain it is read against.
    """
    inputs = await _read(
        site_id, pseudogene_inputs(site_id, strain_gene, reference_gene)
    )
    check = await _in_a_slot(
        check_pseudogene_call, inputs.reference, inputs.strain_coding_dna, _CODE
    )
    return PseudogeneCallAudit.model_validate(
        {
            **check.model_dump(),
            "strain_gene": strain_gene,
            "reference_gene": reference_gene,
        }
    )


async def audit_selenoprotein_end(
    site_id: str,
    gene: str,
    reference_gene: str,
) -> SelenoproteinEndAudit:
    """Check whether a gene model ends at the TGA that encodes its selenocysteine.

    STOPS_AT_SEC means the model stops at a TGA and the genome after it
    encodes the reference protein's tail. CONTAINS_SEC means the model
    already holds the selenocysteine.

    Args:
        site_id: VEuPathDB site, for example 'toxodb'.
        gene: The gene whose model is checked.
        reference_gene: A gene whose protein holds the selenocysteine.
    """
    inputs = await _read(site_id, selenoprotein_inputs(site_id, gene, reference_gene))
    check = await _in_a_slot(
        check_sec_stop,
        inputs.model_protein,
        inputs.reference_protein,
        inputs.dna,
        inputs.strand,
        _CODE,
    )
    return SelenoproteinEndAudit.model_validate(
        {**check.model_dump(), "gene": gene, "reference_gene": reference_gene}
    )


async def _length_audit(site_id: str, genes: list[str]) -> GeneLengthAudit:
    inputs = await _read(site_id, length_inputs(site_id, genes))
    dna = inputs.dna
    if dna is None:
        check = LengthCheck.not_checked()
    else:
        check = await _in_a_slot(
            check_length,
            dna.reference_protein,
            dna.model_proteins,
            dna.window,
            dna.code,
        )
    return GeneLengthAudit.model_validate(
        {
            **check.model_dump(),
            **inputs.screen.model_dump(),
            "code": dna.code if dna else None,
            "code_inferred": dna.code_inferred if dna else False,
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
    the genome holds the missing segment on the gene's strand, so the model
    misses it; ASSEMBLY means a gap or a contig end can explain it; ABSENT
    means the genome lacks it; NOT_SHORT means the model holds every window.
    Every other class answers NOT_CHECKED with no genome read, and then
    nsInWindow and atContigEdge are null; organisms, groupMedian,
    groupCopies and groupSpread show what the group holds.

    Args:
        site_id: VEuPathDB site, for example 'plasmodb'.
        gene: The gene whose protein length is checked.
    """
    return await _length_audit(site_id, [gene])


async def audit_gene_split(site_id: str, gene_a: str, gene_b: str) -> GeneLengthAudit:
    """Check whether two neighbouring gene models are one gene split in two.

    Both genes must be coding members of gene_a's ortholog group, next to
    each other in position among their organism's members, on one strand of
    one sequence and at most 20,000 bases apart. The pair is a SPLIT when
    each protein is under 0.85 of its genus median and the two sum to 0.8
    to 1.35 of it. The genome region of a SPLIT pair is then read for the
    protein of the closest single-copy ortholog: SPLIT_CONFIRMED means each
    model holds at least 3 of its windows and the two together hold 60% of
    them; SPLIT_UNCLEAR means they do not. A pair that is not a SPLIT, or
    that the group cannot judge (UNQUALIFIED), answers NOT_CHECKED and reads
    no genome.

    Args:
        site_id: VEuPathDB site, for example 'plasmodb'.
        gene_a: One of the two models, whose ortholog group is read.
        gene_b: The neighbouring model on the same strand.
    """
    return await _length_audit(site_id, [gene_a, gene_b])

"""The served gene-model checks, read from the site the call names."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable

import httpx
from fastmcp.exceptions import ToolError
from veupathdb.errors import VEuPathDBError

from veupathdb_mcp.audit import (
    GeneticCode,
    PseudogeneCallAudit,
    SelenoproteinEndAudit,
    check_pseudogene_call,
    check_sec_stop,
    pseudogene_inputs,
    selenoprotein_inputs,
)
from veupathdb_mcp.tool_errors import ToolErrorPayload
from veupathdb_mcp.tools.refusals import payload_or_error

_CODE = GeneticCode.STANDARD


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
    check = await asyncio.to_thread(
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
    check = check_sec_stop(
        inputs.model_protein,
        inputs.reference_protein,
        inputs.dna,
        inputs.strand,
        _CODE,
    )
    return SelenoproteinEndAudit.model_validate(
        {**check.model_dump(), "gene": gene, "reference_gene": reference_gene}
    )

"""What the pseudogene anatomy reads from a site: the Exon segments of the strain gene
and its reference, and the pseudogene check's inputs, whose strain window it reuses."""

from __future__ import annotations

from itertools import pairwise

from pydantic import BaseModel, ConfigDict
from veupathdb.errors import VEuPathDBErrorCode
from veupathdb.jbrowse import GenomeReader, get_jbrowse_client

from veupathdb_mcp.audit.gene_models import (
    ModelRow,
    longest_transcript,
    model_record,
)
from veupathdb_mcp.audit.genes import GeneRow
from veupathdb_mcp.audit.served import (
    PSEUDOGENE_PAD,
    PseudogeneInputs,
    PseudogenePair,
    no_cds,
    pseudogene_dna,
    pseudogene_pair,
)
from veupathdb_mcp.tool_errors import ToolErrorPayload, tool_error

SEGMENT_TYPE = "Exon"


def model_segments(rows: list[ModelRow]) -> list[tuple[int, int]]:
    return longest_transcript(rows, SEGMENT_TYPE)


class AnatomyInputs(BaseModel):
    model_config = ConfigDict(frozen=True)

    pseudogene: PseudogeneInputs
    segments: list[tuple[int, int]]
    reference_segments: int
    window: str
    window_start: int
    contig_length: int


def _outside(
    strain: GeneRow, segments: list[tuple[int, int]]
) -> ToolErrorPayload | None:
    first, last = strain.start - PSEUDOGENE_PAD, strain.end + PSEUDOGENE_PAD
    if first <= segments[0][0] and segments[-1][1] <= last:
        return None
    return tool_error(
        VEuPathDBErrorCode.VALIDATION_ERROR,
        f"{strain.gene} serves {SEGMENT_TYPE} rows {segments[0][0]}-{segments[-1][1]} "
        f"outside its gene span {strain.start}-{strain.end} and the "
        f"{PSEUDOGENE_PAD} bases read on each side",
    )


def _segment_refusal(
    site_id: str, gene: str, segments: list[tuple[int, int]]
) -> ToolErrorPayload | None:
    if not segments:
        return tool_error(
            VEuPathDBErrorCode.VALIDATION_ERROR,
            f"{gene} has no {SEGMENT_TYPE} rows in its gene model on {site_id}",
        )
    for (a, b), (c, d) in pairwise(segments):
        if c <= b:
            return tool_error(
                VEuPathDBErrorCode.VALIDATION_ERROR,
                f"{gene} serves {SEGMENT_TYPE} rows {a}-{b} and {c}-{d} that "
                f"overlap on {site_id}",
            )
    return None


async def anatomy_inputs(
    site_id: str, strain_gene: str, reference_gene: str
) -> AnatomyInputs | ToolErrorPayload:
    match await pseudogene_pair(site_id, strain_gene, reference_gene):
        case ToolErrorPayload() as refusal:
            return refusal
        case PseudogenePair() as pair:
            strain_id, reference_id = pair.strain.gene, pair.reference.gene
    reference = await model_record(site_id, reference_id)
    reference_model = reference.model
    if (uncoded := no_cds(site_id, reference_id, reference_model)) is not None:
        return uncoded
    strain = await model_record(site_id, strain_id)
    segments = model_segments(strain.rows)
    unread = _segment_refusal(site_id, strain_id, segments) or _outside(
        pair.strain, segments
    )
    if unread is not None:
        return unread
    pseudogene = await pseudogene_dna(
        site_id, pair, strain.model.organism_abbrev, reference
    )
    contig_length = await GenomeReader(get_jbrowse_client(site_id)).sequence_length(
        strain.model.organism_abbrev, pair.strain.sequence_id
    )
    window = pseudogene.strain_window
    return AnatomyInputs(
        pseudogene=pseudogene,
        segments=segments,
        reference_segments=len(model_segments(reference.rows)),
        window=window.sequence,
        window_start=window.start,
        contig_length=contig_length,
    )

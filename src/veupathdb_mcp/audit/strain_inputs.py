"""What the strain check reads from a site: both genes and their proteins, the ortholog
group of the reference, the annotated genes beside the strain gene, and the strain's
genome around it."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field
from veupathdb.errors import VEuPathDBErrorCode
from veupathdb.jbrowse import (
    SequenceNotIndexedError,
    get_jbrowse_client,
    parse_gff_line,
)

from veupathdb_mcp.audit.gene_ids import GeneId, id_pairs
from veupathdb_mcp.audit.gene_models import gene_organism
from veupathdb_mcp.audit.genes import GeneRow, GroupMember, orthologs_of
from veupathdb_mcp.audit.lengths import species_of
from veupathdb_mcp.audit.served import (
    LengthDna,
    length_dna,
    length_span,
    length_window,
    located,
    read_proteins,
)
from veupathdb_mcp.audit.track_reads import (
    organism_tracks,
    tabix_reader,
    tabix_track,
)
from veupathdb_mcp.catalog.group_ids import is_group_id, is_residual
from veupathdb_mcp.tool_errors import ToolErrorPayload, tool_error

ANNOTATION_TRACK = "genomeAndProteome/gff/annotated_transcripts.gff.gz"
ANNOTATION_MAX_GROUPS = 4
STRAIN_STORE_READS = 1 + ANNOTATION_MAX_GROUPS


class StrainInputs(BaseModel):
    model_config = ConfigDict(frozen=True)

    strain: GeneRow
    reference: GeneRow
    strain_protein: str
    reference_protein: str
    group: list[GroupMember] | None
    gene_ids: list[GeneId] = Field(min_length=2, max_length=2)


def _unpaired(strain: GeneRow, reference: GeneRow) -> ToolErrorPayload | None:
    if species_of(strain.organism) != species_of(reference.organism):
        return tool_error(
            VEuPathDBErrorCode.VALIDATION_ERROR,
            f"{strain.gene} ({strain.organism}) and {reference.gene} "
            f"({reference.organism}) are not strains of one species",
        )
    if strain.organism == reference.organism:
        return tool_error(
            VEuPathDBErrorCode.VALIDATION_ERROR,
            f"{strain.gene} and {reference.gene} are both genes of {strain.organism}; "
            "a strain gene is read against another strain of its species",
        )
    group = reference.ortholog_group
    if not is_group_id(group):
        return tool_error(
            VEuPathDBErrorCode.VALIDATION_ERROR,
            f"{strain.gene} and {reference.gene} lie in no ortholog group ({group}); "
            "a strain gene is read against a member of its own ortholog group",
        )
    if strain.ortholog_group != reference.ortholog_group:
        return tool_error(
            VEuPathDBErrorCode.VALIDATION_ERROR,
            f"{strain.gene} lies in {strain.ortholog_group} and {reference.gene} in "
            f"{reference.ortholog_group}; a strain gene is read against a member of "
            "its own ortholog group",
        )
    return None


async def strain_inputs(
    site_id: str, strain_gene: str, reference_gene: str
) -> StrainInputs | ToolErrorPayload:
    if strain_gene == reference_gene:
        return tool_error(
            VEuPathDBErrorCode.VALIDATION_ERROR, f"the pair names {strain_gene} twice"
        )
    match await located(site_id, [strain_gene, reference_gene]):
        case ToolErrorPayload() as refusal:
            return refusal
        case rows:
            strain, reference = rows[strain_gene], rows[reference_gene]
    if (unpaired := _unpaired(strain, reference)) is not None:
        return unpaired
    match await read_proteins(site_id, [strain.gene, reference.gene]):
        case ToolErrorPayload() as refusal:
            return refusal
        case proteins:
            pass
    residual = is_residual(reference.ortholog_group)
    return StrainInputs(
        strain=strain,
        reference=reference,
        strain_protein=proteins[strain.gene],
        reference_protein=proteins[reference.gene],
        group=None
        if residual
        else (await orthologs_of(site_id, reference.gene)).members,
        gene_ids=id_pairs([strain_gene, reference_gene], rows),
    )


def _missing(inputs: StrainInputs) -> int:
    return len(inputs.reference_protein) - len(inputs.strain_protein)


class _GeneTags(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    own: tuple[str, ...] = Field(default=(), validation_alias="ID")


def annotated_genes(lines: list[str]) -> set[str]:
    features = [parse_gff_line(line) for line in lines]
    return {
        gene
        for feature in features
        if feature.kind.lower().endswith("gene")
        for gene in _GeneTags.model_validate(feature.attributes).own[:1]
    }


async def _genes_in(
    site_id: str, abbrev: str, seqid: str, span: tuple[int, int]
) -> set[str] | ToolErrorPayload:
    client = get_jbrowse_client(site_id)
    track = tabix_track(await organism_tracks(client, abbrev), ANNOTATION_TRACK)
    if track is None:
        return tool_error(
            VEuPathDBErrorCode.VALIDATION_ERROR,
            f"{abbrev} lists no {ANNOTATION_TRACK} track on {site_id}",
        )
    reader = tabix_reader(client)
    try:
        groups = await reader.chunk_group_count(track, seqid, *span)
    except SequenceNotIndexedError:
        return set()
    if groups > ANNOTATION_MAX_GROUPS:
        return tool_error(
            VEuPathDBErrorCode.VALIDATION_ERROR,
            f"the annotation over {seqid}:{span[0]}-{span[1]} lies in {groups} "
            f"chunk groups; at most {ANNOTATION_MAX_GROUPS} are read",
        )
    return annotated_genes(await reader.lines(track, seqid, *span))


async def paralogs_in_window(
    site_id: str, inputs: StrainInputs
) -> list[str] | ToolErrorPayload:
    strain = inputs.strain
    same = {
        member.gene
        for member in inputs.group or []
        if member.organism == strain.organism and member.gene != strain.gene
    }
    if not same:
        return []
    abbrev = await gene_organism(site_id, strain.gene)
    span = length_span([strain], _missing(inputs))
    match await _genes_in(site_id, abbrev, strain.sequence_id, span):
        case ToolErrorPayload() as refusal:
            return refusal
        case genes:
            return sorted(same & genes)


async def strain_dna(
    site_id: str, inputs: StrainInputs
) -> LengthDna | ToolErrorPayload:
    match length_window([inputs.strain], _missing(inputs)):
        case ToolErrorPayload() as refusal:
            return refusal
        case span:
            return await length_dna(
                site_id,
                [inputs.strain],
                span,
                inputs.reference_protein,
                [inputs.strain_protein],
            )

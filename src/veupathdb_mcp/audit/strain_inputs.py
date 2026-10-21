"""What the strain check reads from a site: both genes and their proteins, the ortholog
group of the reference, and the strain's genome around the strain gene."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field
from veupathdb.errors import VEuPathDBErrorCode

from veupathdb_mcp.audit.gene_ids import GeneId, id_pairs
from veupathdb_mcp.audit.genes import GeneRow, orthologs_of
from veupathdb_mcp.audit.lengths import (
    is_orthology_group,
    is_residual_group,
    species_of,
)
from veupathdb_mcp.audit.served import (
    LengthDna,
    length_dna,
    length_span,
    length_window,
    located,
    read_proteins,
)
from veupathdb_mcp.tool_errors import ToolErrorPayload, tool_error


class StrainInputs(BaseModel):
    model_config = ConfigDict(frozen=True)

    strain: GeneRow
    reference: GeneRow
    strain_protein: str
    reference_protein: str
    group: list[GeneRow] | None
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
    if not (is_orthology_group(group) or is_residual_group(group)):
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
    residual = is_residual_group(reference.ortholog_group)
    return StrainInputs(
        strain=strain,
        reference=reference,
        strain_protein=proteins[strain.gene],
        reference_protein=proteins[reference.gene],
        group=None if residual else await orthologs_of(site_id, reference.gene),
        gene_ids=id_pairs([strain_gene, reference_gene], rows),
    )


def _missing(inputs: StrainInputs) -> int:
    return len(inputs.reference_protein) - len(inputs.strain_protein)


def paralogs_in_window(inputs: StrainInputs) -> list[str]:
    strain = inputs.strain
    first, last = length_span([strain], _missing(inputs))
    return sorted(
        row.gene
        for row in inputs.group or []
        if row.organism == strain.organism
        and row.gene != strain.gene
        and row.sequence_id == strain.sequence_id
        and row.start <= last
        and row.end >= first
    )


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

"""Over-representation analysis on a gene list given by value."""

from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict, Field, model_validator
from veupathdb.errors import (
    ValidationError,
    VEuPathDBError,
    VEuPathDBErrorCode,
)
from veupathdb.logging import get_logger
from veupathdb.model import CamelModel
from veupathdb.wdk.wdk_models import (
    WDKEnrichmentResponse,
    WDKEnrichmentRowBase,
    WDKGoEnrichmentRow,
    WDKPathwayEnrichmentRow,
    WDKWordEnrichmentRow,
)

from veupathdb_mcp.wdk.enrichment.service import EnrichmentService
from veupathdb_mcp.wdk.enrichment.types import (
    ALL_ENRICHMENT_ANALYSIS_TYPES,
    BackgroundSource,
    EnrichmentAnalysisType,
    EnrichmentTerm,
)
from veupathdb_mcp.wdk.gene_set_steps import (
    build_enrichment_params_from_gene_ids,
)

logger = get_logger(__name__)

MAX_ENRICHMENT_GENE_IDS = 200
"""The largest gene list one enrichment call accepts."""


def _wire_key(model: type[BaseModel], field_name: str) -> str:
    """The JSON key a WDK model field is read from."""
    alias = model.model_fields[field_name].alias
    if alias is None:
        msg = f"{model.__name__}.{field_name} carries no WDK wire key"
        raise TypeError(msg)
    return alias


class EnrichmentSourceColumns(CamelModel):
    """The WDK keys an analysis type's identity fields come from.

    The enrichment plugins name their own columns and a wrong name yields an
    empty column rather than an error, so each analysis reports the two it read.
    """

    model_config = ConfigDict(frozen=True)

    envelope: str
    term_id: str
    term_name: str


def _columns(
    row_model: type[WDKEnrichmentRowBase],
    term_id_field: str,
    term_name_field: str,
) -> EnrichmentSourceColumns:
    return EnrichmentSourceColumns(
        envelope=_wire_key(WDKEnrichmentResponse, "result_data"),
        term_id=_wire_key(row_model, term_id_field),
        term_name=_wire_key(row_model, term_name_field),
    )


SOURCE_COLUMNS: Mapping[EnrichmentAnalysisType, EnrichmentSourceColumns] = {
    "go_function": _columns(WDKGoEnrichmentRow, "go_id", "go_term"),
    "go_component": _columns(WDKGoEnrichmentRow, "go_id", "go_term"),
    "go_process": _columns(WDKGoEnrichmentRow, "go_id", "go_term"),
    "pathway": _columns(WDKPathwayEnrichmentRow, "pathway_id", "pathway_name"),
    "word": _columns(WDKWordEnrichmentRow, "word", "pathway_name"),
}


class EnrichedAnalysis(CamelModel):
    """One analysis type's terms, and the columns they were read from."""

    model_config = ConfigDict(frozen=True)

    analysis_type: EnrichmentAnalysisType
    source_columns: EnrichmentSourceColumns
    terms: list[EnrichmentTerm] = Field(default_factory=list)
    error: str | None = None

    @model_validator(mode="after")
    def _columns_belong_to_the_analysis(self) -> "EnrichedAnalysis":
        expected = SOURCE_COLUMNS[self.analysis_type]
        if self.source_columns != expected:
            msg = f"{self.analysis_type} is read through {expected}"
            raise ValueError(msg)
        return self


class GeneIdEnrichment(CamelModel):
    """Over-representation results for a gene list given by value."""

    model_config = ConfigDict(frozen=True)

    site_id: str
    gene_count: int
    background: BackgroundSource
    analyses: list[EnrichedAnalysis]


def _clean_gene_ids(gene_ids: list[str]) -> list[str]:
    """Trim, drop blanks and repeats, and refuse a list out of bounds."""
    ids = list(dict.fromkeys(gid.strip() for gid in gene_ids if gid.strip()))
    if not ids:
        msg = "gene_ids holds no gene identifier."
        raise ValidationError(detail=msg)
    if len(ids) > MAX_ENRICHMENT_GENE_IDS:
        msg = (
            f"gene_ids holds {len(ids)} identifiers; one enrichment call takes "
            f"at most {MAX_ENRICHMENT_GENE_IDS}."
        )
        raise ValidationError(detail=msg)
    return ids


async def enrich_gene_ids_by_value(
    site_id: str,
    gene_ids: list[str],
    background: BackgroundSource,
    enrichment_types: list[EnrichmentAnalysisType] | None = None,
) -> GeneIdEnrichment:
    """Run over-representation analysis on a gene list, with no stored set.

    The genes become a temporary WDK dataset addressed by a locus-tag search,
    and that step is the one every analysis type runs on.
    """
    ids = _clean_gene_ids(gene_ids)
    types = list(enrichment_types or ALL_ENRICHMENT_ANALYSIS_TYPES)

    search_name, parameters, record_type = await build_enrichment_params_from_gene_ids(
        site_id, ids
    )
    results, errors = await EnrichmentService(background).run_batch(
        site_id=site_id,
        analysis_types=types,
        search_name=search_name,
        record_type=record_type,
        parameters=parameters,
    )
    if len(errors) == len(types):
        raise VEuPathDBError(
            code=VEuPathDBErrorCode.INTERNAL_ERROR,
            title="Enrichment analysis failed",
            status=500,
            detail="; ".join(errors),
        )

    logger.info(
        "Enrichment ran on a gene list",
        site_id=site_id,
        gene_count=len(ids),
        analyses=[r.analysis_type for r in results],
    )
    return GeneIdEnrichment(
        site_id=site_id,
        gene_count=len(ids),
        background=background,
        analyses=[
            EnrichedAnalysis(
                analysis_type=r.analysis_type,
                source_columns=SOURCE_COLUMNS[r.analysis_type],
                terms=r.terms,
                error=r.error,
            )
            for r in results
        ],
    )

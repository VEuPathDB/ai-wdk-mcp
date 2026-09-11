"""Converts raw WDK enrichment results into structured terms and results."""

from pydantic import JsonValue, ValidationError
from veupathdb import JSONObject
from veupathdb.wdk import (
    WDKEnrichmentResponse,
    WDKEnrichmentRowBase,
    WDKGoEnrichmentRow,
    WDKPathwayEnrichmentRow,
    WDKWordEnrichmentRow,
)

from veupathdb_mcp.wdk.enrichment.html import parse_result_genes_html
from veupathdb_mcp.wdk.enrichment.types import (
    EnrichmentAnalysisType,
    EnrichmentResult,
    EnrichmentTerm,
)

ANALYSIS_TYPE_MAP: dict[EnrichmentAnalysisType, str] = {
    "go_function": "go-enrichment",
    "go_component": "go-enrichment",
    "go_process": "go-enrichment",
    "pathway": "pathway-enrichment",
    "word": "word-enrichment",
}

GO_ONTOLOGY_MAP: dict[EnrichmentAnalysisType, str] = {
    "go_function": "Molecular Function",
    "go_component": "Cellular Component",
    "go_process": "Biological Process",
}

_GO_ANALYSIS_TYPES: frozenset[EnrichmentAnalysisType] = frozenset(
    {"go_function", "go_component", "go_process"}
)


def upsert_enrichment_result(
    results: list[EnrichmentResult],
    new: EnrichmentResult,
) -> None:
    """Replace the result with the same analysis type in place, or append it."""
    for i, existing in enumerate(results):
        if existing.analysis_type == new.analysis_type:
            results[i] = new
            return
    results.append(new)


def parse_enrichment_response(result: JsonValue) -> WDKEnrichmentResponse:
    """Validate a raw WDK analysis result into a typed envelope."""
    if not isinstance(result, dict):
        return WDKEnrichmentResponse()
    try:
        return WDKEnrichmentResponse.model_validate(result)
    except ValidationError:
        return WDKEnrichmentResponse()


def _extract_genes(result_genes: str) -> tuple[int, list[str]]:
    """Extract the gene count and gene IDs from a WDK result-genes field.

    The field holds either an HTML link that carries both, or a plain count.
    """
    if "<" in result_genes:
        return parse_result_genes_html(result_genes)
    try:
        return int(float(result_genes)), []
    except ValueError, TypeError:
        return 0, []


def _row_to_term(
    row: WDKEnrichmentRowBase,
    term_id: str,
    term_name: str,
) -> EnrichmentTerm:
    """Map a WDK enrichment row to a domain term.

    The raw string values pass through unchanged. The term model coerces them.
    """
    gene_count, genes = _extract_genes(row.result_genes)
    return EnrichmentTerm.model_validate(
        {
            "term_id": term_id,
            "term_name": term_name,
            "gene_count": gene_count,
            "background_count": row.bgd_genes,
            "fold_enrichment": row.fold_enrich,
            "odds_ratio": row.odds_ratio,
            "p_value": row.p_value,
            "fdr": row.benjamini,
            "bonferroni": row.bonferroni,
            "genes": genes,
        }
    )


def parse_enrichment_terms(
    rows: list[JSONObject],
    analysis_type: EnrichmentAnalysisType = "go_process",
) -> list[EnrichmentTerm]:
    """Parse WDK enrichment result rows into structured terms."""
    terms: list[EnrichmentTerm] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            wdk_row: WDKEnrichmentRowBase
            term_id: str
            term_name: str
            if analysis_type in _GO_ANALYSIS_TYPES:
                go_row = WDKGoEnrichmentRow.model_validate(row)
                wdk_row, term_id, term_name = go_row, go_row.go_id, go_row.go_term
            elif analysis_type == "pathway":
                pw_row = WDKPathwayEnrichmentRow.model_validate(row)
                wdk_row, term_id, term_name = (
                    pw_row,
                    pw_row.pathway_id,
                    pw_row.pathway_name,
                )
            else:
                wd_row = WDKWordEnrichmentRow.model_validate(row)
                wdk_row, term_id, term_name = wd_row, wd_row.word, wd_row.pathway_name
            terms.append(_row_to_term(wdk_row, term_id, term_name))
        except ValidationError:
            continue
    return terms

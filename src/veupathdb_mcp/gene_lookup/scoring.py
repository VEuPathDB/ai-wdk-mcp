"""Gene-specific relevance scoring for text search results."""

from veupathdb_mcp.gene_lookup.rerank import (
    score_field_quality,
    score_text_match,
)

from .organism import score_organism_match
from .result import GeneResult

_W_GENE_ID = 100.0
_W_GENE_NAME = 40.0
_W_ORGANISM = 30.0
_W_PRODUCT = 35.0
_W_DISPLAY_NAME = 25.0
_W_FIELD_QUALITY = 20.0
_EXACT_BONUS = 80.0
_NEAR_EXACT_MATCH_THRESHOLD = 0.95


def score_gene_relevance(query: str, result: GeneResult) -> float:
    """Score a gene result's relevance to *query*.

    Higher is better.  The score is an additive combination of how well
    the query matches the gene ID, gene name, organism, and product,
    plus a bonus/penalty based on which site-search fields matched.

    An extra bonus is awarded when the query exactly matches a descriptive
    field (product, displayName) so that exact hits always rank above
    incidental fuzzy overlap from shared tokens like "alpha" or "2".
    """
    mf_list = result.matched_fields or []

    id_score = score_text_match(query, result.gene_id)
    name_score = score_text_match(query, result.gene_name)
    disp_score = score_text_match(query, result.display_name)
    prod_score = score_text_match(query, result.product)

    score = 0.0
    score += _W_GENE_ID * id_score
    score += _W_GENE_NAME * name_score
    score += _W_DISPLAY_NAME * disp_score
    score += _W_ORGANISM * score_organism_match(query, result.organism)
    score += _W_PRODUCT * prod_score
    score += _W_FIELD_QUALITY * score_field_quality(mf_list)

    # Exact/near-exact match bonus — ensures "alpha tubulin 2" beats
    # "casein kinase 2, alpha subunit" which only shares tokens.
    best_desc = max(prod_score, disp_score, name_score)
    if best_desc >= _NEAR_EXACT_MATCH_THRESHOLD:
        score += _EXACT_BONUS * best_desc

    return score

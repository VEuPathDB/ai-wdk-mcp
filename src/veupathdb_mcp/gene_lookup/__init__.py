"""Gene record lookup: free text against site search, and IDs against WDK.

Both reads are stateless. Neither creates a step or a strategy.
"""

from veupathdb_mcp.gene_lookup.lookup import GeneSearchResult, lookup_genes_by_text
from veupathdb_mcp.gene_lookup.organisms import list_organisms
from veupathdb_mcp.gene_lookup.result import GeneResult
from veupathdb_mcp.gene_lookup.site_search import (
    SITE_SEARCH_PAGE_LIMIT,
    SITE_SEARCH_STREAM_LIMIT,
    fetch_site_search_genes,
    stream_site_search_gene_ids,
)
from veupathdb_mcp.gene_lookup.wdk import (
    MAX_GENE_IDS,
    GeneResolveResult,
    normalize_gene_ids,
    resolve_gene_ids,
)

__all__ = [
    "MAX_GENE_IDS",
    "SITE_SEARCH_PAGE_LIMIT",
    "SITE_SEARCH_STREAM_LIMIT",
    "GeneResolveResult",
    "GeneResult",
    "GeneSearchResult",
    "fetch_site_search_genes",
    "list_organisms",
    "lookup_genes_by_text",
    "normalize_gene_ids",
    "resolve_gene_ids",
    "stream_site_search_gene_ids",
]

"""Gene record lookup service.

Provides two complementary lookup strategies:

1. **Text search** -- uses VEuPathDB site-search (Solr) to find genes by name,
   symbol, product description, or any free text.  Results are filtered to the
   ``gene`` document type so only gene records are returned.

2. **ID resolution** -- uses the WDK stateless standard reporter endpoint
   (``POST /record-types/{rt}/searches/{search}/reports/standard``) to fetch
   metadata for a list of known gene IDs.  Useful for validating IDs or
   retrieving product names / organisms for IDs obtained from literature.

Both approaches are read-only and do not create steps or strategies.
"""

from .lookup import GeneSearchResult, lookup_genes_by_text
from .organisms import list_organisms
from .result import GeneResult
from .wdk import (
    MAX_GENE_IDS,
    GeneResolveResult,
    normalize_gene_ids,
    resolve_gene_ids,
)

__all__ = [
    "MAX_GENE_IDS",
    "GeneResolveResult",
    "GeneResult",
    "GeneSearchResult",
    "list_organisms",
    "lookup_genes_by_text",
    "normalize_gene_ids",
    "resolve_gene_ids",
]

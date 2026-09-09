"""Literature search API clients."""

from veupathdb_mcp.research.literature.clients.arxiv import ArxivClient
from veupathdb_mcp.research.literature.clients.crossref import CrossrefClient
from veupathdb_mcp.research.literature.clients.europepmc import EuropePmcClient
from veupathdb_mcp.research.literature.clients.openalex import OpenAlexClient
from veupathdb_mcp.research.literature.clients.preprint import PreprintClient
from veupathdb_mcp.research.literature.clients.pubmed import PubmedClient
from veupathdb_mcp.research.literature.clients.semanticscholar import (
    SemanticScholarClient,
)

__all__ = [
    "ArxivClient",
    "CrossrefClient",
    "EuropePmcClient",
    "OpenAlexClient",
    "PreprintClient",
    "PubmedClient",
    "SemanticScholarClient",
]

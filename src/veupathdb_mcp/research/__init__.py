"""veupathdb-research-mcp: literature and web search, served over MCP."""

from veupathdb_mcp.research.citations import (
    Citation,
    LiteratureFilters,
    LiteratureOutputOptions,
    LiteratureSort,
    LiteratureSource,
)
from veupathdb_mcp.research.models import (
    LiteratureSearchOut,
    PaperOut,
    SourceRef,
    WebResultOut,
    WebSearchOut,
)
from veupathdb_mcp.research.server import (
    RESEARCH_MAX_CALL_SECONDS,
    SERVER_NAME,
    SOURCES_PART_KIND,
    TOOLS,
    build_server,
)
from veupathdb_mcp.research.settings import (
    ResearchSettings,
    get_research_settings,
    use_research_settings_source,
)
from veupathdb_mcp.research.tools import literature_search, web_search

__all__ = [
    "RESEARCH_MAX_CALL_SECONDS",
    "SERVER_NAME",
    "SOURCES_PART_KIND",
    "TOOLS",
    "Citation",
    "LiteratureFilters",
    "LiteratureOutputOptions",
    "LiteratureSearchOut",
    "LiteratureSort",
    "LiteratureSource",
    "PaperOut",
    "ResearchSettings",
    "SourceRef",
    "WebResultOut",
    "WebSearchOut",
    "build_server",
    "get_research_settings",
    "literature_search",
    "use_research_settings_source",
    "web_search",
]

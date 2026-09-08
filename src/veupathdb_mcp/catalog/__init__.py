"""Catalog services: sites, record types, searches, parameter metadata.

Single source of truth for catalog/discovery logic used by both:
- HTTP transport (`transport/http/routers/sites.py`)
- AI tools (`ai/tools/catalog_tools.py`, etc.)
"""

from veupathdb_mcp.catalog._param_filters import has_contrast_sibling
from veupathdb_mcp.catalog.eda_backed import (
    EdaBackedSearch,
    eda_backed_guidance,
    eda_backed_search,
    is_eda_backed,
    is_upload_sentinel_vocabulary,
    list_eda_backed,
)
from veupathdb_mcp.catalog.models import RecordTypeInfo, SearchMatch
from veupathdb_mcp.catalog.parameters import (
    expand_search_details_with_params,
    get_refreshed_dependent_params,
    get_search_parameters,
    get_search_parameters_tool,
    lookup_phyletic_codes,
    validate_search_params,
)
from veupathdb_mcp.catalog.search_inspection import (
    SearchInspection,
    UnknownSearchError,
    VocabNarrowing,
    inspect_search,
    read_parameter_options,
)
from veupathdb_mcp.catalog.searches import (
    SearchQueryRejection,
    VagueSearchQueryError,
    browse_search_categories,
    get_raw_record_types,
    get_raw_searches,
    list_searches,
    list_transforms,
    read_search_definition,
    resolve_search_record_type,
    search_for_searches,
)
from veupathdb_mcp.catalog.sites import (
    get_record_types,
    list_sites,
)

__all__ = [
    "EdaBackedSearch",
    "RecordTypeInfo",
    "SearchInspection",
    "SearchMatch",
    "SearchQueryRejection",
    "UnknownSearchError",
    "VagueSearchQueryError",
    "VocabNarrowing",
    "browse_search_categories",
    "eda_backed_guidance",
    "eda_backed_search",
    "expand_search_details_with_params",
    "get_raw_record_types",
    "get_raw_searches",
    "get_record_types",
    "get_refreshed_dependent_params",
    "get_search_parameters",
    "get_search_parameters_tool",
    "has_contrast_sibling",
    "inspect_search",
    "is_eda_backed",
    "is_upload_sentinel_vocabulary",
    "list_eda_backed",
    "list_searches",
    "list_sites",
    "list_transforms",
    "lookup_phyletic_codes",
    "read_parameter_options",
    "read_search_definition",
    "resolve_search_record_type",
    "search_for_searches",
    "validate_search_params",
]

"""The tools the WDK server serves, callable by a host in its own process."""

from veupathdb_mcp.tools.catalog_tools import (
    browse_search_categories,
    get_parameter_options,
    get_search_overview,
    list_record_types,
    list_searches,
    list_transforms,
    lookup_phyletic_codes,
    search_example_plans,
    search_for_searches,
)
from veupathdb_mcp.tools.user_tools import (
    enrich_gene_ids,
    get_ai_expression_summary,
    get_step_download_url,
    get_step_estimated_size,
    get_step_sample_records,
    lookup_gene_records,
    resolve_gene_ids_to_records,
    run_control_tests_on_search,
)

__all__ = [
    "browse_search_categories",
    "enrich_gene_ids",
    "get_ai_expression_summary",
    "get_parameter_options",
    "get_search_overview",
    "get_step_download_url",
    "get_step_estimated_size",
    "get_step_sample_records",
    "list_record_types",
    "list_searches",
    "list_transforms",
    "lookup_gene_records",
    "lookup_phyletic_codes",
    "resolve_gene_ids_to_records",
    "run_control_tests_on_search",
    "search_example_plans",
    "search_for_searches",
]

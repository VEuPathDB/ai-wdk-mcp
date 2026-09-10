"""The site catalog: sites, record types, searches and parameter metadata."""

from veupathdb_mcp.catalog._param_filters import has_contrast_sibling
from veupathdb_mcp.catalog.discovery_service import get_discovery_service
from veupathdb_mcp.catalog.eda_backed import (
    COMPUTE_QUERY,
    EDA_ANALYSIS_SPEC_PARAM,
    EDA_DATASET_ID_PARAM,
    SUBSET_QUERY,
    EdaBackedSearch,
    EdaStepRequest,
    eda_backed_guidance,
    eda_backed_search,
    is_eda_backed,
    is_upload_sentinel_vocabulary,
    list_eda_backed,
)
from veupathdb_mcp.catalog.models import (
    UNIVERSAL_SEARCHES,
    ParamSpecResponse,
    RecordTypeInfo,
    SearchMatch,
)
from veupathdb_mcp.catalog.overview_formatting import (
    SearchOverviewResult,
    format_search_overview,
)
from veupathdb_mcp.catalog.param_adapters import adapt_param_specs_from_search
from veupathdb_mcp.catalog.param_dag import (
    ParamFetcher,
    ResolvedParams,
    UnknownParameterError,
    resolve_params_with_intent,
    wdk_fetch_at,
)
from veupathdb_mcp.catalog.param_discovery import fetch_search_details
from veupathdb_mcp.catalog.param_formatting import (
    PHYLETIC_LIST_PARAMS,
    FilterFieldInfo,
    GetParameterOptionsResult,
    ParameterInfo,
    ParameterNotOnSearch,
    ParentContextRequired,
    format_param_info_typed,
)
from veupathdb_mcp.catalog.param_intent import (
    ParamIntent,
    Provenance,
    contrast_role_of,
    is_direction_param,
)
from veupathdb_mcp.catalog.param_phyletic import (
    PhyleticNoSelection,
    PhyleticUnresolvedProposal,
    derive_phyletic_overrides,
    is_phyletic_sheet,
)
from veupathdb_mcp.catalog.param_resolution import SearchParametersResult
from veupathdb_mcp.catalog.param_sheet import SheetEntry, build_sheet
from veupathdb_mcp.catalog.param_specs_formatting import (
    build_param_specs,
    build_param_specs_from_list,
)
from veupathdb_mcp.catalog.param_validation import (
    ResolvedSearch,
    ValidatedParams,
    ValidationCallbacks,
    ValidationResponse,
    resolve_search_details,
    validate_parameters,
)
from veupathdb_mcp.catalog.parameters import (
    expand_search_details_with_params,
    get_refreshed_dependent_params,
    get_search_parameters,
    get_search_parameters_tool,
    lookup_phyletic_codes,
    validate_search_params,
)
from veupathdb_mcp.catalog.radio_pairs import (
    RADIO_OFF,
    RadioPairIssue,
    check_radio_pairs,
    radio_pairs,
)
from veupathdb_mcp.catalog.search_context import get_search_params_under_context
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
    assign_step_record_classes,
    browse_search_categories,
    get_raw_record_types,
    get_raw_searches,
    list_searches,
    list_transforms,
    make_record_type_resolver,
    read_search_definition,
    resolve_search_record_type,
    search_for_searches,
)
from veupathdb_mcp.catalog.sites import (
    get_record_types,
    list_sites,
)
from veupathdb_mcp.catalog.validation_callbacks import make_validation_callbacks

__all__ = [
    "COMPUTE_QUERY",
    "EDA_ANALYSIS_SPEC_PARAM",
    "EDA_DATASET_ID_PARAM",
    "PHYLETIC_LIST_PARAMS",
    "RADIO_OFF",
    "SUBSET_QUERY",
    "UNIVERSAL_SEARCHES",
    "EdaBackedSearch",
    "EdaStepRequest",
    "FilterFieldInfo",
    "GetParameterOptionsResult",
    "ParamFetcher",
    "ParamIntent",
    "ParamSpecResponse",
    "ParameterInfo",
    "ParameterNotOnSearch",
    "ParentContextRequired",
    "PhyleticNoSelection",
    "PhyleticUnresolvedProposal",
    "Provenance",
    "RadioPairIssue",
    "RecordTypeInfo",
    "ResolvedParams",
    "ResolvedSearch",
    "SearchInspection",
    "SearchMatch",
    "SearchOverviewResult",
    "SearchParametersResult",
    "SearchQueryRejection",
    "SheetEntry",
    "UnknownParameterError",
    "UnknownSearchError",
    "VagueSearchQueryError",
    "ValidatedParams",
    "ValidationCallbacks",
    "ValidationResponse",
    "VocabNarrowing",
    "adapt_param_specs_from_search",
    "assign_step_record_classes",
    "browse_search_categories",
    "build_param_specs",
    "build_param_specs_from_list",
    "build_sheet",
    "check_radio_pairs",
    "contrast_role_of",
    "derive_phyletic_overrides",
    "eda_backed_guidance",
    "eda_backed_search",
    "expand_search_details_with_params",
    "fetch_search_details",
    "format_param_info_typed",
    "format_search_overview",
    "get_discovery_service",
    "get_raw_record_types",
    "get_raw_searches",
    "get_record_types",
    "get_refreshed_dependent_params",
    "get_search_parameters",
    "get_search_parameters_tool",
    "get_search_params_under_context",
    "has_contrast_sibling",
    "inspect_search",
    "is_direction_param",
    "is_eda_backed",
    "is_phyletic_sheet",
    "is_upload_sentinel_vocabulary",
    "list_eda_backed",
    "list_searches",
    "list_sites",
    "list_transforms",
    "lookup_phyletic_codes",
    "make_record_type_resolver",
    "make_validation_callbacks",
    "radio_pairs",
    "read_parameter_options",
    "read_search_definition",
    "resolve_params_with_intent",
    "resolve_search_details",
    "resolve_search_record_type",
    "search_for_searches",
    "validate_parameters",
    "validate_search_params",
    "wdk_fetch_at",
]

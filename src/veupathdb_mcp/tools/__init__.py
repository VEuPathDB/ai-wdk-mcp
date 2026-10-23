"""The tools the WDK server serves, callable by a host in its own process."""

from veupathdb_mcp.tools.audit_anatomy_tools import audit_pseudogene_anatomy
from veupathdb_mcp.tools.audit_busco_tools import audit_genome_priority
from veupathdb_mcp.tools.audit_evidence_tools import (
    audit_gene_evidence,
    audit_genome_provenance,
)
from veupathdb_mcp.tools.audit_fusion_tools import audit_gene_fusion
from veupathdb_mcp.tools.audit_genome_pseudogene_calls_tools import (
    audit_genome_pseudogene_calls,
)
from veupathdb_mcp.tools.audit_intron_tools import audit_intron_support
from veupathdb_mcp.tools.audit_missing_tools import audit_missing_gene
from veupathdb_mcp.tools.audit_organelle_tools import audit_organelle_gene
from veupathdb_mcp.tools.audit_strain_tools import audit_strain_model
from veupathdb_mcp.tools.audit_tools import (
    audit_gene_length,
    audit_gene_split,
    audit_pseudogene_call,
    audit_selenoprotein_end,
)
from veupathdb_mcp.tools.catalog_tools import (
    browse_search_categories,
    build_phyletic_expression,
    get_parameter_options,
    get_search_overview,
    get_search_param_specs,
    list_record_types,
    list_searches,
    list_transforms,
    lookup_phyletic_codes,
    rank_experiments_elsewhere,
    read_experiment,
    resolve_search_parameters,
    search_catalog_index,
    search_example_plans,
    search_for_searches,
    validate_search_parameters,
)
from veupathdb_mcp.tools.user_tools import (
    count_plan_steps,
    create_gene_set_step,
    enrich_gene_ids,
    get_ai_expression_summary,
    get_step_download_url,
    get_step_estimated_size,
    get_step_gene_ids,
    get_step_sample_records,
    lookup_gene_records,
    resolve_gene_ids_to_records,
    run_control_tests_on_search,
    run_control_tests_on_step,
)

__all__ = [
    "audit_gene_evidence",
    "audit_gene_fusion",
    "audit_gene_length",
    "audit_gene_split",
    "audit_genome_priority",
    "audit_genome_provenance",
    "audit_genome_pseudogene_calls",
    "audit_intron_support",
    "audit_missing_gene",
    "audit_organelle_gene",
    "audit_pseudogene_anatomy",
    "audit_pseudogene_call",
    "audit_selenoprotein_end",
    "audit_strain_model",
    "browse_search_categories",
    "build_phyletic_expression",
    "count_plan_steps",
    "create_gene_set_step",
    "enrich_gene_ids",
    "get_ai_expression_summary",
    "get_parameter_options",
    "get_search_overview",
    "get_search_param_specs",
    "get_step_download_url",
    "get_step_estimated_size",
    "get_step_gene_ids",
    "get_step_sample_records",
    "list_record_types",
    "list_searches",
    "list_transforms",
    "lookup_gene_records",
    "lookup_phyletic_codes",
    "rank_experiments_elsewhere",
    "read_experiment",
    "resolve_gene_ids_to_records",
    "resolve_search_parameters",
    "run_control_tests_on_search",
    "run_control_tests_on_step",
    "search_catalog_index",
    "search_example_plans",
    "search_for_searches",
    "validate_search_parameters",
]

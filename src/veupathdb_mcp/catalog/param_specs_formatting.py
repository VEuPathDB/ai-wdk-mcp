"""Format WDK parameter objects into normalized ParamSpecResponse DTOs.

Owns the mapping from integration-layer WDK parameter types to the
service-layer ``ParamSpecResponse`` shape that transport returns.
"""

from collections.abc import Sequence

from veupathdb.wdk import WDKParameter, WDKSearch

from veupathdb_mcp.catalog.models import ParamSpecResponse


def build_param_specs_from_list(
    params: Sequence[WDKParameter],
) -> list[ParamSpecResponse]:
    """Convert a list of WDK parameters to normalized ParamSpecResponse objects.

    All subtype-specific fields (vocabulary, min/max, etc.) are declared on
    ``WDKBaseParameter`` with safe defaults, so no isinstance narrowing is
    needed — every ``WDKParameter`` variant exposes them directly.
    """
    results: list[ParamSpecResponse] = []
    for param in params:
        is_multi = param.type == "multi-pick-vocabulary"

        results.append(
            ParamSpecResponse(
                name=param.name,
                display_name=param.display_name or None,
                type=param.type,
                allow_empty_value=param.allow_empty_value,
                allow_multiple_values=is_multi,
                multi_pick=is_multi,
                min_selected_count=param.min_selected_count,
                max_selected_count=param.max_selected_count,
                count_only_leaves=param.count_only_leaves,
                initial_display_value=param.initial_display_value,
                vocabulary=param.vocabulary,
                min=param.min,
                max=param.max,
                is_number=param.is_number,
                increment=param.increment,
                display_type=param.display_type or None,
                is_visible=param.is_visible,
                group=param.group or None,
                dependent_params=list(param.dependent_params),
                help=param.help,
                ontology=list(param.ontology) if param.type == "filter" else None,
                filter_data_type_display_name=(
                    param.filter_data_type_display_name
                    if param.type == "filter"
                    else None
                ),
                parsers=(
                    list(param.parsers) if param.type == "input-dataset" else None
                ),
                default_id_list=(
                    param.default_id_list if param.type == "input-dataset" else None
                ),
                record_class_name=(
                    param.record_class_name if param.type == "input-dataset" else None
                ),
            ),
        )
    results.sort(key=lambda s: s.name)
    return results


def build_param_specs(search: WDKSearch) -> list[ParamSpecResponse]:
    """Convert a WDK search's parameters to normalized ParamSpecResponse objects."""
    return build_param_specs_from_list(search.parameters or [])

"""Adapters: WDK integration types -> domain ParamSpecNormalized.

These functions accept integration-layer types (WDKSearch, WDKBaseParameter)
and return domain types (ParamSpecNormalized). They live in the service
layer because they bridge integration and domain.
"""

from veupathdb.domain.parameters import ParamSpecNormalized
from veupathdb.wdk import WDKParameter, WDKSearch


def adapt_param_from_wdk(param: WDKParameter) -> ParamSpecNormalized:
    """Convert a typed WDK parameter to the canonical spec."""
    return ParamSpecNormalized(
        name=param.name,
        param_type=param.type,
        allow_empty_value=param.allow_empty_value,
        min_selected_count=param.min_selected_count,
        max_selected_count=param.max_selected_count,
        vocabulary=param.vocabulary,
        count_only_leaves=param.count_only_leaves,
        min_date=param.min_date,
        max_date=param.max_date,
        is_number=param.is_number,
        min=float(param.min) if param.min is not None else None,
        max=float(param.max) if param.max is not None else None,
        increment=float(param.increment) if param.increment is not None else None,
        max_length=param.length if param.length > 0 else None,
        display_type=param.display_type,
        is_visible=param.is_visible,
        group=param.group,
        dependent_params=tuple(param.dependent_params),
        help=param.help,
        initial_display_value=param.initial_display_value,
    )


def adapt_param_specs_from_search(search: WDKSearch) -> dict[str, ParamSpecNormalized]:
    """Build normalized param specs from a typed WDK search."""
    if not search.parameters:
        return {}
    return {p.name: adapt_param_from_wdk(p) for p in search.parameters}

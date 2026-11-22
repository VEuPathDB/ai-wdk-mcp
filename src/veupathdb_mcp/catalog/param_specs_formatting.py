"""Format WDK parameter objects into normalized ParamSpecResponse DTOs.

Owns the mapping from integration-layer WDK parameter types to the
service-layer ``ParamSpecResponse`` shape that transport returns.
"""

from collections.abc import Sequence

from pydantic import JsonValue
from veupathdb.domain.parameters import shown_stated
from veupathdb.wdk import WDKParameter, WDKSearch

from veupathdb_mcp.catalog.models import (
    ParamSpecResponse,
    StatedParamSpec,
    _ParamSpecFields,
)
from veupathdb_mcp.catalog.param_adapters import held_default


def _spec[S: _ParamSpecFields](
    spec: type[S], param: WDKParameter, **held: JsonValue
) -> S:
    is_multi = param.type == "multi-pick-vocabulary"
    return spec(
        name=param.name,
        display_name=param.display_name or None,
        type=param.type,
        allow_empty_value=param.allow_empty_value,
        allow_multiple_values=is_multi,
        multi_pick=is_multi,
        min_selected_count=param.min_selected_count,
        max_selected_count=param.max_selected_count,
        count_only_leaves=param.count_only_leaves,
        vocabulary=param.vocabulary,
        min=param.min,
        max=param.max,
        is_number=param.is_number,
        increment=param.increment,
        display_type=param.display_type or None,
        is_visible=param.is_visible,
        is_read_only=param.is_read_only,
        group=param.group or None,
        dependent_params=list(param.dependent_params),
        help=param.help,
        ontology=list(param.ontology) if param.type == "filter" else None,
        filter_data_type_display_name=(
            param.filter_data_type_display_name if param.type == "filter" else None
        ),
        parsers=list(param.parsers) if param.type == "input-dataset" else None,
        default_id_list=(
            param.default_id_list if param.type == "input-dataset" else None
        ),
        record_class_name=(
            param.record_class_name if param.type == "input-dataset" else None
        ),
        **held,
    )


def build_param_specs_from_list(
    params: Sequence[WDKParameter],
) -> list[ParamSpecResponse]:
    """Each parameter's normalized spec, with its default as WDK holds it."""
    return sorted(
        (
            _spec(ParamSpecResponse, p, initial_display_value=p.initial_display_value)
            for p in params
        ),
        key=lambda s: s.name,
    )


def build_stated_param_specs(search: WDKSearch) -> list[StatedParamSpec]:
    """Each parameter's normalized spec, with its default in the form it is stated."""
    specs = (
        _spec(StatedParamSpec, p, default=_stated_default(p))
        for p in search.parameters or []
    )
    return sorted(specs, key=lambda s: s.name)


def _stated_default(param: WDKParameter) -> JsonValue:
    held = held_default(param)
    return None if held is None else shown_stated(held)


def build_param_specs(search: WDKSearch) -> list[ParamSpecResponse]:
    """Convert a WDK search's parameters to normalized ParamSpecResponse objects."""
    return build_param_specs_from_list(search.parameters or [])

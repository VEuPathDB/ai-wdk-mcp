"""Resolution of a WDK filter parameter against its ontology facets."""

from __future__ import annotations

from veupathdb.domain.parameters import (
    FilterProposal,
    FilterValue,
    ParamValue,
    UnboundParameter,
)

from veupathdb_mcp.catalog._param_binding import OverrideMap
from veupathdb_mcp.catalog.param_formatting import ParameterInfo

_CONTRAST_PREFIXES: tuple[tuple[str, str], ...] = (("ref", "comp"), ("comp", "ref"))


def has_contrast_sibling(info: ParameterInfo, infos: list[ParameterInfo]) -> bool:
    """Reports whether this filter param is one half of a reference and comparison
    sample pair. Both halves taking the empty all-samples filter is a degenerate
    contrast, so the pair is surfaced instead of auto-resolved."""
    name = info.name
    for this, other in _CONTRAST_PREFIXES:
        prefix = f"{this}_"
        if name.startswith(prefix):
            sibling = f"{other}_{name[len(prefix) :]}"
            return any(i.name == sibling and i.param_kind == "filter" for i in infos)
    return False


def _contrast_open_slot(info: ParameterInfo) -> UnboundParameter:
    return UnboundParameter(
        param_name=info.name,
        question=(
            f"Choose the sample group for {info.display_name}: a "
            f"reference-vs-comparison contrast needs DISTINCT groups on each "
            f"side, not all samples on both."
        ),
        options=[
            FilterValue(
                filters=[facet.clause(FilterProposal(field=facet.term, value=[member]))]
            ).to_wire()
            for facet in info.facets().root
            if not facet.ranged
            for member in facet.members
        ],
    )


def _resolve_filter_param(
    info: ParameterInfo, infos: list[ParameterInfo], overrides: OverrideMap
) -> ParamValue | UnboundParameter:
    """Resolves a filter param to a value, or returns an UnboundParameter for an
    unspecified half of a contrast pair."""
    stated = overrides.get(info.name)
    if stated is not None:
        return stated
    if has_contrast_sibling(info, infos):
        return _contrast_open_slot(info)
    return FilterValue()

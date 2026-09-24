"""Which searches a separation can intersect with a gene list, and the organism binding.

The rules are WDK's: a boolean compares one record class (WDK-STEP-008), a
search with an answer parameter is a transform (WDK-STEP-001), and a search that
takes a dataset scores the controls against themselves (WDK-PARAM-009).
"""

from veupathdb.domain.parameters import match_exact_option
from veupathdb.wdk import WDKSearch

from veupathdb_mcp.catalog import (
    OverrideMap,
    ParameterInfo,
    ResolvedParams,
    is_eda_backed,
)
from veupathdb_mcp.separation.models import SkipReason

GENE_RECORD_CLASS = "transcript"

_PICKS = frozenset({"single-pick-vocabulary", "multi-pick-vocabulary"})


def search_skip(search: WDKSearch) -> SkipReason | None:
    """Why the catalog's listing of a search rules it out, or None."""
    if search.output_record_class_name != GENE_RECORD_CLASS:
        return "not_a_gene_search"
    if search.allowed_primary_input_record_class_names:
        return "transform"
    if is_eda_backed(search):
        return "needs_an_analysis"
    return None


def params_skip(infos: list[ParameterInfo]) -> SkipReason | None:
    """Why a search's parameters rule it out, or None."""
    if any(info.param_kind == "input-dataset" for info in infos):
        return "takes_a_gene_list"
    return None


def binding_gap(resolved: ResolvedParams) -> str:
    """The required parameters a binding left without a value, comma-separated."""
    names = set(resolved.unresolved_required)
    names.update(slot.param_name for slot in resolved.open_slots)
    return ", ".join(sorted(names))


def organism_overrides(infos: list[ParameterInfo], organisms: list[str]) -> OverrideMap:
    """Bind the organisms into every pick parameter whose vocabulary holds them all.

    The organism parameter has no one name across searches, so its vocabulary
    finds it. A single pick takes one organism only.
    """
    overrides: OverrideMap = {}
    if not organisms:
        return overrides
    for info in infos:
        if info.param_kind not in _PICKS:
            continue
        options = info.vocabulary()
        terms = [match_exact_option(options, organism) for organism in organisms]
        held = [term for term in terms if term is not None]
        if len(held) != len(organisms):
            continue
        if info.param_kind == "multi-pick-vocabulary":
            overrides[info.name] = held
        elif len(held) == 1:
            overrides[info.name] = held[0]
    return overrides

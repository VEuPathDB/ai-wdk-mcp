"""Reads which parameter values WDK supplied rather than accepted."""

from __future__ import annotations

from collections.abc import Callable, Mapping

from pydantic import TypeAdapter, ValidationError
from veupathdb.domain.parameters import (
    FilterClauseKey,
    FilterValue,
    ParamSpecNormalized,
    ParamValue,
    to_wire,
)

_SELECTION_ADAPTER: TypeAdapter[list[str]] = TypeAdapter(list[str])

Comparable = str | frozenset[str] | frozenset[FilterClauseKey]
"""A value reduced to what it states, so serialization cannot differ."""


def _selection(wire: str) -> frozenset[str]:
    """The values a vocabulary wire form selects, order and encoding aside."""
    if not wire:
        return frozenset()
    try:
        return frozenset(_SELECTION_ADAPTER.validate_json(wire))
    except ValidationError:
        return frozenset({wire})


def _clauses(wire: str) -> frozenset[FilterClauseKey]:
    """The clauses a filter wire form states, order and key order aside."""
    return FilterValue.model_validate_json(wire or '{"filters": []}').clause_set


_COMPARATORS: dict[str, Callable[[str], Comparable]] = {
    "single-pick-vocabulary": _selection,
    "multi-pick-vocabulary": _selection,
    "filter": _clauses,
}

_UNREPORTED_TYPES = frozenset({"input-step"})
"""An input-step value is the wiring the caller made, never a WDK choice."""


def _comparable(spec: ParamSpecNormalized | None, wire: str) -> Comparable:
    reader = _COMPARATORS.get(spec.param_type) if spec is not None else None
    return reader(wire) if reader is not None else wire


def substituted_params(
    *,
    sent: Mapping[str, ParamValue],
    echoed: Mapping[str, str],
    specs: Mapping[str, ParamSpecNormalized],
    values_were_read: bool,
) -> list[str]:
    """Params whose echoed value is WDK's rather than the caller's.

    Each kind is compared as what it states: a vocabulary as its selection, a
    filter as its clauses, everything else as its wire form. A definition WDK
    built without reading the caller's values describes no caller at all, so
    only the params left unset are read from it.
    """
    sent_wire = {name: to_wire(value) for name, value in sent.items()}
    supplied: list[str] = []
    for name, echoed_value in echoed.items():
        spec = specs.get(name)
        if spec is not None and spec.param_type in _UNREPORTED_TYPES:
            continue
        theirs = _comparable(spec, echoed_value)
        ours = sent_wire.get(name)
        if ours is None:
            if theirs:
                supplied.append(name)
            continue
        if not values_were_read:
            continue
        if _comparable(spec, ours) != theirs:
            supplied.append(name)
    return sorted(supplied)

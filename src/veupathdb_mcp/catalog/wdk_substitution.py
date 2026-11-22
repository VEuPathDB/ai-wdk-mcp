"""Reads which parameter values WDK supplied rather than accepted."""

from __future__ import annotations

from collections.abc import Mapping

from veupathdb.domain.parameters import (
    FilterValue,
    MultiPickValue,
    ParameterCanonicalizer,
    ParamSpecNormalized,
    ParamValue,
    as_param_kind,
    same_param_value,
    to_wire,
)

_UNREPORTED_TYPES = frozenset({"input-step"})
"""An input-step value is the wiring the caller made, never a WDK choice."""


def _states_something(value: ParamValue | None) -> bool:
    match value:
        case None | MultiPickValue(values=[]) | FilterValue(filters=[], empty=False):
            return False
        case _:
            return bool(to_wire(value))


def substituted_params(
    *,
    sent: Mapping[str, ParamValue],
    echoed: Mapping[str, str],
    specs: Mapping[str, ParamSpecNormalized],
    values_were_read: bool,
) -> list[str]:
    """Params whose echoed value is WDK's rather than the caller's.

    Each value is read in its declared kind and compared with ``same_param_value``.
    A definition WDK built without reading the caller's values describes no caller at all, so
    only the params left unset are read from it.
    """
    reader = ParameterCanonicalizer(dict(specs))
    theirs = reader.held(dict(echoed))
    ours = reader.held({name: to_wire(value) for name, value in sent.items()})
    supplied: list[str] = []
    for name in echoed:
        spec = specs.get(name)
        if spec is not None and spec.param_type in _UNREPORTED_TYPES:
            continue
        if name not in sent:
            if _states_something(theirs.get(name)):
                supplied.append(name)
            continue
        if not values_were_read:
            continue
        kind = None if spec is None else as_param_kind(spec.param_type)
        if not same_param_value(name, kind, ours[name], theirs[name]):
            supplied.append(name)
    return sorted(supplied)

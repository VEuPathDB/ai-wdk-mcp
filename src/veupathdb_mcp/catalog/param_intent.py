from __future__ import annotations

from enum import StrEnum
from typing import Literal

from veupathdb.domain.parameters import VocabOption
from veupathdb.model import CamelModel

from veupathdb_mcp.catalog.param_formatting import ParameterInfo

# One value, or the several values a multi-pick param takes.
ParamAnswer = str | list[str]


class Provenance(StrEnum):
    """Where a bound value came from. A default must stay distinguishable."""

    STATED = "stated"
    DEFAULTED = "defaulted"


class IntentMatch(CamelModel):
    """A value together with how it was found."""

    value: ParamAnswer
    provenance: Provenance


class ParamIntent(CamelModel):
    """The criterion text a resolution runs against."""

    text: str = ""


def match_option(options: list[VocabOption], hint: str) -> str | None:
    """Map a free-text hint to a vocab value: exact match first, then substring."""
    h = hint.lower()
    for o in options:
        if h in (o.value.lower(), o.display.lower()):
            return o.value
    for o in options:
        if h in o.display.lower() or h in o.value.lower():
            return o.value
    return None


_REFERENCE_MARKERS = ("_ref_", "_ref", "reference")
_COMPARISON_MARKERS = ("_comp_", "_comp", "comparison", "comparator")


# A contrast is between sample groups.
_CONTRAST_SUBJECT_MARKERS = ("sample", "group")
# WDK names an aggregation pair with the same reference/comparison markers.
_AGGREGATION_MARKERS = ("operation", "min_max_avg")


def is_aggregation_param(name: str) -> bool:
    """Whether a param selects how to aggregate a side rather than which samples
    that side contains."""
    return any(m in name.lower() for m in _AGGREGATION_MARKERS)


def contrast_role_of(name: str) -> Literal["reference", "comparison"] | None:
    """Contrast role from a param name or label alone."""
    haystack = name.lower()
    if any(m in haystack for m in _AGGREGATION_MARKERS):
        return None
    if not any(m in haystack for m in _CONTRAST_SUBJECT_MARKERS):
        return None
    if any(m in haystack for m in _COMPARISON_MARKERS):
        return "comparison"
    if any(m in haystack for m in _REFERENCE_MARKERS):
        return "reference"
    return None


def is_direction_param(name: str) -> bool:
    low = name.lower()
    return "regulated_dir" in low or low.endswith("_dir") or "direction" in low


_ROLE_SLOT = "\x00"


def contrast_pair_key(name: str) -> str:
    """A key shared by the two halves of one contrast pair.

    The role marker is replaced by a slot, so the remaining stem keeps unrelated
    pairs independent.
    """
    low = name.lower()
    for marker in (*_COMPARISON_MARKERS, *_REFERENCE_MARKERS):
        if marker in low:
            return low.replace(marker, _ROLE_SLOT, 1)
    return low


def contrast_role(pi: ParameterInfo) -> Literal["reference", "comparison"] | None:
    """Which side of a differential contrast this sample selector fills.

    WDK computes fold change as comparator against reference, so the two sides
    are not interchangeable.
    """
    return contrast_role_of(f"{pi.name} {pi.display_name}")

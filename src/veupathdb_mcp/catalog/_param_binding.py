"""Binding of one non-filter parameter to a value, an open slot, or nothing."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from pydantic import Field
from veupathdb.domain.parameters.unbound import UnboundParameter
from veupathdb.domain.parameters.value_codec import param_value_from_raw
from veupathdb.domain.parameters.values import ParamValue
from veupathdb.domain.parameters.wdk_vocab import match_exact_option
from veupathdb.model import CamelModel

from veupathdb_mcp.catalog.param_formatting import ParameterInfo
from veupathdb_mcp.catalog.param_intent import (
    IntentMatch,
    ParamIntent,
    Provenance,
    contrast_role,
    is_aggregation_param,
)

_SCALAR_DEFAULTABLE: frozenset[str] = frozenset(
    {"number", "string", "date", "timestamp", "single-pick-vocabulary"}
)
_MAX_SLOT_OPTIONS = 20
# A vocabulary needs two or more options before a shared value is a real choice.
_MIN_VOCAB_SIZE_FOR_DEGENERACY = 2

# An answered open slot holds one value, or a list for a multi-pick slot.
OverrideValue = str | list[str]
OverrideMap = dict[str, OverrideValue]


def _vocab_signature(info: ParameterInfo) -> str | None:
    """Returns a stable signature of the option set, or None when there is no vocabulary."""
    values = info.vocabulary()
    if not values:
        return None
    return "|".join(sorted(o.value for o in values))


def _sole_claim(value: OverrideValue | None) -> str | None:
    """Returns the single vocabulary option this resolution claims.

    A multi-pick selection claims no single option.
    """
    return None if isinstance(value, list) else value


def param_value_for(pi: ParameterInfo, raw: object) -> ParamValue:
    """Builds a ParamValue from a chosen term using the param's ParamKind."""
    return param_value_from_raw(raw, pi.param_kind)


def _single_valid_value(info: ParameterInfo) -> str | None:
    """The one value a vocabulary of exactly one entry allows.

    ``None`` when the param has no vocabulary or offers a choice.
    """
    values = info.vocabulary()
    return values[0].value if len(values) == 1 else None


class ResolvedParam(CamelModel):
    """One bound value with the reason it holds that value."""

    value: ParamValue
    provenance: Provenance


class Unread(CamelModel):
    """A numeric param left with no value while the request states a quantity for it.

    The caller reads the quantity out of the request instead of asking the user,
    so this is not an open slot.
    """

    param_name: str


def _build_value(info: ParameterInfo, value: OverrideValue | None) -> ParamValue | None:
    """Coerces a chosen value into the param's typed value, or None when the kind
    rejects it. Filter params resolve elsewhere."""
    if value is None:
        return None
    try:
        return param_value_for(info, value)
    except ValueError:
        return None


def _apply_override(info: ParameterInfo, value: OverrideValue) -> OverrideValue:
    """Matches a proposed value to the param's vocabulary entry, or passes it through
    for WDK to validate. A list value matches each element on its own.

    The match is exact on the term, on the label, or on a leading accession
    exactly one entry carries. Any other substring names a different entry.
    """
    options = info.vocabulary()
    if not options:
        return value
    if isinstance(value, list):
        return [match_exact_option(options, v) or v for v in value]
    return match_exact_option(options, value) or value


def _resolve_one(info: ParameterInfo, overrides: OverrideMap) -> IntentMatch | None:
    """An override binds as stated; a single valid value binds as the search's own.

    ``None`` leaves the param to the scalar default or to an open slot.
    """
    if info.name in overrides:
        return IntentMatch(
            value=_apply_override(info, overrides[info.name]),
            provenance=Provenance.STATED,
        )
    sole = _single_valid_value(info)
    if sole is not None:
        return IntentMatch(value=sole, provenance=Provenance.DEFAULTED)
    return None


def _is_free_text_query(info: ParameterInfo) -> bool:
    """Reports whether the param is the search's own text query.

    WDK puts an example in the default value of these params, so the default must not
    be inherited. Hidden params and numeric bounds carry real defaults and are excluded.
    """
    return (
        info.param_kind == "string"
        and not info.is_number
        and info.is_visible
        and info.required
        and not info.vocabulary()
    )


# Database accessions: Pfam, PANTHER, InterPro, GO, and EC numbers. The trailing
# boundary is a lookahead because an EC wildcard can end in a hyphen, which
# ``\b`` does not follow.
_ACCESSION_RE = re.compile(
    r"\b(?:[A-Z]{2,}[:_]?\d{3,}|\d+(?:\.[\d-]+){2,})(?![0-9A-Za-z])",
    re.IGNORECASE,
)
_QUANTITY_RE = re.compile(r"(?<![0-9A-Za-z_.:-])\d+(?:\.\d+)?(?![0-9A-Za-z_:-])")


def _states_a_quantity(
    info: ParameterInfo, text: str, siblings: tuple[ParameterInfo, ...]
) -> bool:
    """Whether the request names a number this numeric param could answer.

    A default is a reasonable answer to a question nobody asked. It is not a
    reasonable answer to one the request already answered, so a stated quantity
    holds the default back and the param is reported unread instead.
    """
    if not info.is_number or not info.default_value or not text:
        return False
    without_identifiers = _ACCESSION_RE.sub(" ", text)
    stated = {m.group(0) for m in _QUANTITY_RE.finditer(without_identifiers)}
    if not stated:
        return False
    # With several numeric slots on one search there is nothing to say which
    # one the number belongs to. Grouping the ends of a range together was
    # measured against the gold corpus and cost seven correct defaults while
    # preventing no wrong value, so the slots are counted as they come.
    numeric_slots = [s for s in siblings if s.is_number and s.default_value]
    if len(numeric_slots) > 1:
        return False
    # A default that equals a stated quantity is the stated quantity.
    return not any(_same_number(value, info.default_value) for value in stated)


def _same_number(left: str, right: str) -> bool:
    try:
        return float(left) == float(right)
    except ValueError:
        return False


def _scalar_default(info: ParameterInfo) -> str | None:
    """Returns the param default when the kind is a defaultable scalar or vocabulary.
    The caller applies the degenerate-pair check."""
    if not info.default_value or info.param_kind not in _SCALAR_DEFAULTABLE:
        return None
    if _is_free_text_query(info):
        return None
    return info.default_value


def _curated_multi_default(info: ParameterInfo) -> list[str] | None:
    """Returns a multi-pick param's non-empty list default, which is the curated
    selection. A param with an empty default returns None, so an override or an open
    slot decides it.
    """
    if info.param_kind != "multi-pick-vocabulary" or not info.default_value:
        return None
    try:
        parsed = json.loads(info.default_value)
    except TypeError, ValueError:
        return None
    if not isinstance(parsed, list) or not parsed:
        return None
    return [str(v) for v in parsed]


class _VocabLedger(CamelModel):
    """Tracks which vocabulary values siblings from the same option set have taken.

    Two params from one option set must not take the same value. The ledger also
    records whether an override stated the value or a default supplied it.
    """

    taken: dict[str, set[str]] = Field(default_factory=dict)
    pinned: dict[str, set[str]] = Field(default_factory=dict)
    claimant: dict[str, dict[str, str]] = Field(default_factory=dict)

    def claim(self, signature: str, value: str, name: str, *, pinned: bool) -> None:
        self.taken.setdefault(signature, set()).add(value)
        self.claimant.setdefault(signature, {})[value] = name
        if pinned:
            self.pinned.setdefault(signature, set()).add(value)

    def duplicates_sibling(self, info: ParameterInfo, value: str) -> bool:
        """Reports whether a sibling from the identical vocabulary already took the
        value. A single-option vocabulary is exempt because no other value exists.
        """
        if is_aggregation_param(f"{info.name} {info.display_name}"):
            # Aggregation selectors are not a contrast. The same operation on both
            # sides is correct.
            return False
        if len(info.vocabulary()) < _MIN_VOCAB_SIZE_FOR_DEGENERACY:
            return False
        signature = _vocab_signature(info)
        return signature is not None and value in self.taken.get(signature, set())

    def sole_remaining_option(
        self, info: ParameterInfo, taken_value: str
    ) -> str | None:
        """Returns the single option left once siblings take theirs.

        This applies only when an explicit override pinned the colliding value. A
        defaulted sibling gives no direction, so the caller asks the user instead.
        """
        signature = _vocab_signature(info)
        if signature is None or taken_value not in self.pinned.get(signature, set()):
            return None
        taken = self.taken.get(signature, set())
        remaining = [o.value for o in info.vocabulary() if o.value not in taken]
        return remaining[0] if len(remaining) == 1 else None

    def sole_remaining_after_authoritative(self, info: ParameterInfo) -> str | None:
        """Returns the one option left once an authoritative sibling takes its own.

        A reference slot has no candidate of its own, so a single remaining option is
        the forced answer.
        """
        signature = _vocab_signature(info)
        if signature is None or not self.pinned.get(signature):
            return None
        taken = self.taken.get(signature, set())
        remaining = [o.value for o in info.vocabulary() if o.value not in taken]
        return remaining[0] if len(remaining) == 1 else None

    def release_default_holding(
        self, info: ParameterInfo, wanted: str, overrides: OverrideMap
    ) -> str | None:
        """Frees a value from a defaulted claimant so an override can take it.

        An override is authoritative and a default is not. Returns the evicted param
        name so the caller unbinds and re-resolves it.
        """
        signature = _vocab_signature(info)
        if signature is None:
            return None
        holder = self.claimant.get(signature, {}).get(wanted)
        if holder is None or holder == info.name or holder in overrides:
            return None
        self.taken.get(signature, set()).discard(wanted)
        self.claimant.get(signature, {}).pop(wanted, None)
        self.pinned.setdefault(signature, set()).add(wanted)
        return holder


def _open_slot(info: ParameterInfo) -> UnboundParameter:
    """Builds a question for the user."""
    options = info.vocabulary()
    return UnboundParameter(
        param_name=info.name,
        question=f"Choose a value for {info.display_name}",
        options=[o.value for o in options][:_MAX_SLOT_OPTIONS],
    )


@dataclass(frozen=True)
class _Resolution:
    """Everything the walk needs to decide one parameter's value."""

    intent: ParamIntent
    overrides: OverrideMap
    siblings: tuple[ParameterInfo, ...] = ()


def _settle_value(
    info: ParameterInfo,
    value: OverrideValue | None,
    ledger: _VocabLedger,
    *,
    is_user_choice: bool,
    default_held_back: bool,
) -> OverrideValue | None:
    """Apply the scalar default and the degenerate-pair rules to a read value."""
    if value is None and not default_held_back:
        value = _scalar_default(info)
    if value is None and contrast_role(info) == "reference":
        value = ledger.sole_remaining_after_authoritative(info)
    claimed = _sole_claim(value)
    if (
        claimed is not None
        and not is_user_choice
        and ledger.duplicates_sibling(info, claimed)
    ):
        # A sibling holds this value. Take the forced remainder when one option is left.
        return ledger.sole_remaining_option(info, claimed)
    return value


def _resolve_nonfilter(
    info: ParameterInfo,
    res: _Resolution,
    ledger: _VocabLedger,
) -> ResolvedParam | UnboundParameter | Unread | None:
    """Resolves a non-filter param from an override, then a single valid value, then
    the scalar default, then an open slot. An override outranks the degenerate-pair
    check. Unread means the request states a quantity the default must not answer.
    None means the param is optional and unset."""
    is_user_choice = info.name in res.overrides
    if not is_user_choice:
        curated = _curated_multi_default(info)
        if curated is not None:
            return ResolvedParam(
                value=param_value_for(info, curated), provenance=Provenance.DEFAULTED
            )
    match = _resolve_one(info, res.overrides)
    provenance = match.provenance if match is not None else Provenance.DEFAULTED
    read = match.value if match is not None else None
    held_back = read is None and _states_a_quantity(info, res.intent.text, res.siblings)
    value = _settle_value(
        info,
        read,
        ledger,
        is_user_choice=is_user_choice,
        default_held_back=held_back,
    )
    if value is None and held_back:
        return Unread(param_name=info.name)
    resolved = _build_value(info, value)
    if resolved is None or value is None:
        return _open_slot(info) if info.required else None
    signature = _vocab_signature(info)
    if signature is not None:
        # Only a supplied value is authoritative. A scalar default is not.
        claimed = _sole_claim(value)
        if claimed is not None:
            ledger.claim(signature, claimed, info.name, pinned=is_user_choice)
    return ResolvedParam(value=resolved, provenance=provenance)

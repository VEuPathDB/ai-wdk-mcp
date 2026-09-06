"""Shared WDK helpers for record parsing, attribute inspection, and analysis
parameter merging."""

from collections.abc import Sequence

from pydantic import JsonValue
from veupathdb.json_types import JSONObject
from veupathdb.wdk.wdk_models import (
    WDKAttributeField,
    WDKRecordInstance,
)
from veupathdb.wdk.wdk_parameters import WDKParameter

from veupathdb_mcp.wdk.enrichment.params import (
    encode_vocab_params,
    extract_default_params,
)

_SORTABLE_WDK_TYPES = {"number", "float", "integer", "double"}

DETAIL_ATTRIBUTE_LIMIT = 50
"""Maximum attributes to request for one record detail.

A WDK record type can have thousands of attributes, and a request for all of
them times out.
"""

_SCORE_ATTRIBUTE_KEYWORDS = {
    "score",
    "e_value",
    "evalue",
    "bit_score",
    "bitscore",
    "p_value",
    "pvalue",
    "fold_change",
    "log_fc",
    "confidence",
}


def is_sortable(attr_type: str | None) -> bool:
    """Return ``True`` when a WDK attribute type supports numeric sorting."""
    if not attr_type:
        return False
    return attr_type.lower() in _SORTABLE_WDK_TYPES


def is_suggested_score(name: str) -> bool:
    """Return ``True`` when an attribute name looks like a score."""
    lower = name.lower()
    return any(kw in lower for kw in _SCORE_ATTRIBUTE_KEYWORDS)


def extract_pk(record: WDKRecordInstance) -> str | None:
    """Return the first part of a WDK record composite primary key."""
    if not record.id:
        return None
    return record.id[0].value.strip() or None


def extract_record_ids(
    records: list[WDKRecordInstance],
    *,
    preferred_key: str | None = None,
) -> list[str]:
    """Extract record ids from WDK standard report records. A preferred key
    reads from the record attributes, and the primary key is the fallback."""
    ids: list[str] = []
    for rec in records:
        extracted: str | None = None
        if preferred_key:
            extracted = (rec.attribute_text(preferred_key) or "").strip() or None
        if extracted is None:
            extracted = extract_pk(rec)
        if extracted:
            ids.append(extracted)
    return ids


def order_primary_key(
    pk_parts: list[dict[str, str]],
    pk_refs: list[str],
    pk_defaults: dict[str, str],
) -> list[dict[str, str]]:
    """Reorder and fill primary key parts to match the record class.

    WDK requires the primary key columns in the order that the record class
    declares. A step report can omit columns or return them in another order.
    """
    pk_by_name: dict[str, str] = {
        p.get("name", ""): p.get("value", "") for p in pk_parts
    }
    ordered: list[dict[str, str]] = []
    for col in pk_refs:
        value = pk_by_name.get(col) or pk_defaults.get(col) or ""
        ordered.append({"name": col, "value": value})
    return ordered


def build_attribute_list(attrs: list[WDKAttributeField]) -> list[JsonValue]:
    """Build a normalized attribute list from WDK attribute fields."""
    attributes: list[JsonValue] = []
    for field in attrs:
        sortable = is_sortable(field.type)
        attributes.append(
            {
                "name": field.name,
                "displayName": field.display_name or field.name,
                "help": field.help,
                "type": field.type,
                "isDisplayable": field.is_displayable,
                "isSortable": sortable,
                "isSuggested": sortable and is_suggested_score(field.name),
            }
        )
    return attributes


def extract_detail_attributes(
    attrs: list[WDKAttributeField],
) -> tuple[list[str], dict[str, str]]:
    """Extract attribute names and display names for the record detail view.

    An attribute qualifies when it is in the report or is displayable. The
    result stops at :data:`DETAIL_ATTRIBUTE_LIMIT`.
    """
    names: list[str] = []
    display_names: dict[str, str] = {}
    for field in attrs:
        if not field.is_in_report and not field.is_displayable:
            continue
        names.append(field.name)
        display_names[field.name] = field.display_name or field.name
        if len(names) >= DETAIL_ATTRIBUTE_LIMIT:
            break
    return names, display_names


def merge_analysis_params(
    wdk_params: Sequence[WDKParameter],
    user_params: JSONObject,
) -> JSONObject:
    """Merge WDK form defaults with user-supplied parameters.

    User values sit on top of the defaults, so every required field stays
    present. Vocabulary parameters are re-encoded as JSON arrays, which is the
    form WDK accepts.
    """
    defaults = extract_default_params(wdk_params)
    merged: JSONObject = {**defaults, **user_params}
    return encode_vocab_params(merged, wdk_params)

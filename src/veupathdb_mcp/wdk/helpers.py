"""Shared WDK helpers that read a record's identity."""

from veupathdb.wdk import WDKRecordInstance


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

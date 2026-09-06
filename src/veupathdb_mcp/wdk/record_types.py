"""Shared record-type resolution utility.

Normalizes a user-supplied record type string and matches it against
the available WDK record type objects.  Three matching strategies are
tried in order:

1. **Exact** (case-insensitive) match on canonical name
   (``url_segment``).
2. **Exact** (case-insensitive) match on the ``full_name`` field.
3. **Display name** match -- only accepted when exactly one record type
   has a matching ``display_name`` to avoid ambiguity.

If none of the strategies succeed the function returns ``None``.
"""

from veupathdb.wdk.wdk_models import WDKRecordType


def resolve_record_type(
    available_types: list[WDKRecordType],
    user_input: str,
) -> str | None:
    """Match *user_input* against WDK record-type objects.

    :param available_types: Typed record type list from WDK.
    :param user_input: User-supplied record type string.
    :returns: The canonical (``url_segment``) string for the
        matched record type, or ``None`` if no match is found.
    """
    normalized = user_input.strip().lower()

    # --- Strategy 1: match on canonical name (url_segment) ----------------
    for rt in available_types:
        if rt.url_segment.strip().lower() == normalized:
            return rt.url_segment or None

    # --- Strategy 2: match on full_name -----------------------------------
    for rt in available_types:
        if rt.full_name and rt.full_name.strip().lower() == normalized:
            return rt.url_segment or None

    # --- Strategy 3: match on display_name (single match only) ------------
    display_matches = [
        rt
        for rt in available_types
        if rt.display_name and rt.display_name.strip().lower() == normalized
    ]

    if len(display_matches) == 1:
        return display_matches[0].url_segment or None

    return None

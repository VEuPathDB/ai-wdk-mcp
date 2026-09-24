"""Which searches of a site's catalog the listings offer a researcher."""

from veupathdb.wdk import WDKSearch

# The two operands and the operator, per WDK-STEP-006.
_BOOLEAN_PARAM_COUNT = 3


def is_boolean_search(search: WDKSearch) -> bool:
    """Return True for the boolean question WDK builds for a record class.

    It takes two input steps and one other parameter, the operator.
    """
    return (
        bool(search.allowed_secondary_input_record_class_names)
        and len(search.param_names) == _BOOLEAN_PARAM_COUNT
    )


def is_listed_search(search: WDKSearch) -> bool:
    """Return True for a search a researcher can bind from a listing.

    A search that takes an input step is listed whatever its question set.
    """
    if search.allowed_primary_input_record_class_names:
        return not is_boolean_search(search)
    return not search.full_name.startswith("InternalQuestions.")


def is_chooser_search(search: WDKSearch) -> bool:
    """Return True for a routing search that carries no real parameters.

    WDK marks these with ``hideOperation`` in ``websiteProperties``.
    """
    ws_props = search.properties.get("websiteProperties", [])
    return "hideOperation" in ws_props


def is_ranked_search(search: WDKSearch) -> bool:
    """Return True for a search the ranking and the categories may name."""
    return is_listed_search(search) and not is_chooser_search(search)

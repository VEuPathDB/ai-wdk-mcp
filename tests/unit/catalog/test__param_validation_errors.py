"""The context each parameter-validation failure carries.

A refusal of a value is WDK's own bundle, relayed one row per parameter. A
refusal of the search itself offers the catalog the caller can choose from.
"""

from __future__ import annotations

from typing import Any, cast

from veupathdb.domain.strategy import StepValidation
from veupathdb.errors import ValidationError

from veupathdb_mcp.catalog._param_validation_errors import (
    unknown_search_error,
    unreadable_search_error,
    wdk_rejection_error,
)

_RECORD_TYPE = "transcript"
_SEARCH_NAME = "GenesByTaxon"
_EMPTY = "Cannot be empty."


def _context(exc: ValidationError) -> dict[str, Any]:
    assert exc.errors is not None
    entry = cast("dict[str, Any]", exc.errors[0])
    return cast("dict[str, Any]", entry["context"])


def _bundle(
    *, level: str = "SEMANTIC", is_valid: bool = False, errors: object = None
) -> StepValidation:
    return StepValidation.model_validate(
        {"level": level, "isValid": is_valid, "errors": errors}
    )


class TestUnknownSearch:
    def test_the_hint_is_reported_even_when_there_is_none(self) -> None:
        exc = unknown_search_error(
            search_name=_SEARCH_NAME, record_type=None, record_type_hint=None
        )

        assert exc.title == f"Unknown or invalid search: {_SEARCH_NAME}"
        assert exc.detail == "Search name not found in any record type."
        assert _context(exc) == {"recordType": None, "recordTypeHint": None}


class TestUnreadableSearch:
    def test_the_record_type_catalog_is_offered(self) -> None:
        exc = unreadable_search_error(
            search_name=_SEARCH_NAME,
            record_type=_RECORD_TYPE,
            detail="WDK said no",
            available_searches=["GenesByTaxon", "GenesByLocation"],
            record_type_hint=None,
        )

        assert exc.title == f"Unknown or invalid search: {_SEARCH_NAME}"
        assert exc.detail == "WDK said no"
        assert _context(exc) == {
            "recordType": _RECORD_TYPE,
            "availableSearches": ["GenesByTaxon", "GenesByLocation"],
            "recordTypeHint": None,
        }


class TestWdkRejection:
    def test_one_entry_per_rejected_parameter(self) -> None:
        exc = wdk_rejection_error(
            _bundle(errors={"general": [], "byKey": {"organism": [_EMPTY]}})
        )

        assert exc.title == "Invalid parameter value"
        assert exc.errors == [{"param": "organism", "messages": [_EMPTY]}]

    def test_the_detail_names_the_parameter_before_the_message(self) -> None:
        exc = wdk_rejection_error(
            _bundle(errors={"general": [], "byKey": {"organism": [_EMPTY]}})
        )

        assert exc.detail == f"organism: {_EMPTY}"

    def test_a_general_message_reaches_the_detail(self) -> None:
        exc = wdk_rejection_error(
            _bundle(errors={"general": ["Nothing selected."], "byKey": {}})
        )

        assert exc.detail == "Nothing selected."

    def test_an_empty_verdict_still_says_wdk_refused(self) -> None:
        exc = wdk_rejection_error(_bundle())

        assert exc.detail == "WDK rejected these parameter values."
        assert exc.errors == []

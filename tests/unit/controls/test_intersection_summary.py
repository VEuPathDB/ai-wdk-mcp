"""The published reading of one control-set intersection payload."""

import pytest
from pydantic import ValidationError

from veupathdb_mcp.controls import IntersectionSummary, summarize_intersection


def test_the_summary_reads_the_count_and_the_ids() -> None:
    summary = summarize_intersection(
        {
            "controlsCount": 3,
            "intersectionCount": 2,
            "intersectionIds": ["PF3D7_0100100", "PF3D7_0100200"],
            "intersectionIdsSample": ["PF3D7_0100100"],
            "targetStepId": 41,
            "targetEstimatedSize": 9,
        }
    )

    assert summary == IntersectionSummary(
        intersection_count=2,
        intersection_ids=["PF3D7_0100100", "PF3D7_0100200"],
    )
    assert summary.found_ids == {"PF3D7_0100100", "PF3D7_0100200"}
    assert summary.ids_were_read is True


def test_a_payload_without_ids_reports_that_none_were_read() -> None:
    """A control set over the fetch limit carries a count and no id list."""
    summary = summarize_intersection(
        {"controlsCount": 900, "intersectionCount": 700, "intersectionIds": None}
    )

    assert summary.intersection_count == 700
    assert summary.found_ids == set()
    assert summary.ids_were_read is False


def test_an_empty_id_list_is_not_the_same_as_no_id_list() -> None:
    summary = summarize_intersection(
        {"controlsCount": 2, "intersectionCount": 0, "intersectionIds": []}
    )

    assert summary.found_ids == set()
    assert summary.ids_were_read is True


def test_a_payload_that_names_no_intersection_counts_zero() -> None:
    summary = summarize_intersection({"controlsCount": 2})

    assert summary.intersection_count == 0
    assert summary.ids_were_read is False


def test_the_summary_is_frozen() -> None:
    summary = summarize_intersection({"intersectionCount": 1, "intersectionIds": ["a"]})

    with pytest.raises(ValidationError, match="frozen"):
        summary.intersection_count = 2

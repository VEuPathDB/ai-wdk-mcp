from __future__ import annotations

import httpx
import pytest
import respx
from tests._support.column_site import (
    BUILD_STEP,
    EXON_BINS,
    STEP,
    USER,
    ColumnSite,
    column_site,
)
from veupathdb.auth_context import veupathdb_auth_token_ctx
from veupathdb.errors import DataParsingError, WDKError

from veupathdb_mcp.wdk import (
    DEFAULT_COLUMN_COUNT_TOP,
    MAX_COLUMN_COUNT_TOP,
    ColumnNotCountedError,
    count_by_column,
    list_step_columns,
)

__all__ = ["column_site"]

SITE = "plasmodb"
COUNTABLE = ["exon_count", "gene_product", "organism", "primary_key"]
ORGANISM_REPORT = f"POST /users/{USER}/steps/{STEP}/columns/organism/reports/byValue"


async def test_a_string_column_is_ranked_by_count_with_its_exact_values(
    column_site: ColumnSite,
) -> None:
    counts = await count_by_column(SITE, STEP, "organism")

    assert (counts.kind, counts.display_name, counts.total_records) == (
        "string",
        "Organism",
        797,
    )
    assert [(row.value, row.count) for row in counts.values] == [
        ("Plasmodium falciparum 3D7", 310),
        ("Plasmodium vivax P01", 310),
        ("Plasmodium berghei ANKA", 120),
        ("Plasmodium yoelii yoelii 17X", 45),
        ("Plasmodium knowlesi strain H", 12),
    ]
    assert (counts.distinct_values, counts.bins, counts.statistics) == (5, (), None)


async def test_top_truncates_the_values_and_keeps_the_distinct_count(
    column_site: ColumnSite,
) -> None:
    counts = await count_by_column(SITE, STEP, "organism", top=2)

    assert [row.value for row in counts.values] == [
        "Plasmodium falciparum 3D7",
        "Plasmodium vivax P01",
    ]
    assert (counts.distinct_values, counts.total_records) == (5, 797)


async def test_a_number_column_answers_the_bins_and_statistics_wdk_gives(
    column_site: ColumnSite,
) -> None:
    counts = await count_by_column(SITE, STEP, "exon_count")

    assert counts.kind == "number"
    assert counts.values == ()
    assert [bin_.value for bin_ in counts.bins] == EXON_BINS
    assert (counts.bins[0].bin_label, counts.bins[-1].bin_label) == (
        "[1.0,2.0)",
        "[20.0,21.0)",
    )
    assert counts.statistics is not None
    assert (
        counts.statistics.subset_min,
        counts.statistics.subset_max,
        counts.statistics.subset_mean,
    ) == (1.0, 20.0, 3.4)
    assert (counts.total_records, counts.distinct_values) == (sum(EXON_BINS), 19)


async def test_an_unknown_column_is_refused_naming_the_countable_ones_before_a_report(
    column_site: ColumnSite,
) -> None:
    with pytest.raises(ColumnNotCountedError) as refused:
        await count_by_column(SITE, STEP, "taxon_name")

    assert refused.value.countable == tuple(COUNTABLE)
    assert refused.value.data_type is None
    assert "taxon_name" in str(refused.value.detail)
    assert ", ".join(COUNTABLE) in str(refused.value.detail)
    assert column_site.posts() == []


@pytest.mark.parametrize(
    ("step_id", "column", "data_type"),
    [
        (STEP, "overview", "OTHER"),
        (STEP, "matched_result", "STRING"),
        (STEP, "wdk_weight", "NUMBER"),
        (BUILD_STEP, "release_date", "DATE"),
    ],
)
async def test_a_column_that_cannot_be_counted_is_refused_before_a_report(
    column_site: ColumnSite, step_id: int, column: str, data_type: str
) -> None:
    with pytest.raises(ColumnNotCountedError) as refused:
        await count_by_column(SITE, step_id, column)

    assert refused.value.data_type == data_type
    assert column in str(refused.value.detail)
    assert column_site.posts() == []


async def test_a_refused_report_raises(column_site: ColumnSite) -> None:
    column_site.reports["organism"] = httpx.Response(500, text="report failed")

    with pytest.raises(WDKError):
        await count_by_column(SITE, STEP, "organism")


async def test_an_unreadable_report_raises(column_site: ColumnSite) -> None:
    column_site.reports["organism"] = httpx.Response(200, json={"histogram": "x"})

    with pytest.raises(DataParsingError):
        await count_by_column(SITE, STEP, "organism")


@pytest.mark.parametrize("top", [0, MAX_COLUMN_COUNT_TOP + 1])
async def test_a_top_outside_its_bounds_sends_no_request(
    column_site: ColumnSite, top: int
) -> None:
    with pytest.raises(ValueError, match=str(top)):
        await count_by_column(SITE, STEP, "organism", top=top)

    assert column_site.requests == []


def test_top_defaults_to_twenty_and_stops_at_two_hundred() -> None:
    assert (DEFAULT_COLUMN_COUNT_TOP, MAX_COLUMN_COUNT_TOP) == (20, 200)


async def test_a_count_sends_one_post_and_it_is_the_column_report(
    column_site: ColumnSite,
) -> None:
    await count_by_column(SITE, STEP, "organism")

    assert column_site.posts() == [ORGANISM_REPORT]
    assert column_site.requests == [
        "GET /users/current",
        f"GET /users/{USER}/steps/{STEP}",
        "GET /record-types/transcript?format=expanded",
        "GET /record-types/transcript/searches/GenesByMolecularWeight",
        ORGANISM_REPORT,
    ]


async def test_the_columns_merge_the_record_type_and_the_search(
    column_site: ColumnSite,
) -> None:
    listed = await list_step_columns(SITE, STEP)

    assert (listed.step_id, listed.record_type, listed.search_name) == (
        STEP,
        "transcript",
        "GenesByMolecularWeight",
    )
    assert [
        (column.name, column.display_name, column.data_type, column.countable)
        for column in listed.columns
    ] == [
        ("primary_key", "Gene ID", "STRING", True),
        ("organism", "Organism", "STRING", True),
        ("gene_product", "Product Description", "STRING", True),
        ("exon_count", "# Exons in Gene", "NUMBER", True),
        ("overview", "Overview", "OTHER", False),
        ("matched_result", "Met Search Criteria", "STRING", False),
        ("wdk_weight", "Search Weight", "NUMBER", False),
    ]
    assert column_site.posts() == []


async def test_a_step_with_no_record_type_is_a_parsing_error() -> None:
    reset = veupathdb_auth_token_ctx.set("registered-token")
    with respx.mock(assert_all_called=False) as router:
        router.route().mock(
            side_effect=lambda request: httpx.Response(
                200,
                json={"id": 42}
                if request.url.path.endswith("/users/current")
                else {"id": 3, "searchName": "X", "searchConfig": {"parameters": {}}},
            )
        )
        with pytest.raises(DataParsingError, match="step 3"):
            await list_step_columns(SITE, 3)
    veupathdb_auth_token_ctx.reset(reset)

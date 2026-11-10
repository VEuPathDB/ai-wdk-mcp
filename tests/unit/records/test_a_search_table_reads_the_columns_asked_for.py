from __future__ import annotations

import json
from collections.abc import Iterator

import httpx
import pytest
import respx
from tests._support.record_columns_site import recorded_body

from veupathdb_mcp.records import (
    TableRequest,
    TableRow,
    UnreadableRecordError,
    read_search_table,
)

pytestmark = pytest.mark.usefixtures("catalog")


@pytest.fixture
def wdk() -> Iterator[respx.MockRouter]:
    with respx.mock(assert_all_called=False) as router:
        for root in APP_ROOTS:
            router.get(root).mock(return_value=httpx.Response(200))
        yield router


PORTAL_REPORT = (
    "https://qa.veupathdb.org/veupathdb.qa/service/record-types/organism"
    "/searches/GenomeDataTypes/reports/standard"
)
ORTHOMCL_REPORT = (
    "https://qa.orthomcl.org/orthomcl.qa/service/record-types/helper"
    "/searches/ByDefault/reports/standard"
)
APP_ROOTS = (
    "https://qa.veupathdb.org/veupathdb.qa/app",
    "https://qa.orthomcl.org/orthomcl.qa/app",
)
BUSCO = ["species", "genecount", "busco_genome", "busco_lineage_dataset"]


async def test_the_genome_table_reads_gene_counts_and_busco(
    wdk: respx.MockRouter,
) -> None:
    route = wdk.post(PORTAL_REPORT).mock(
        return_value=httpx.Response(
            200, json=recorded_body("veupathdb_genome_data_types_report.json")
        )
    )

    table = await read_search_table(
        "veupathdb",
        TableRequest(
            record_type="organism",
            search_name="GenomeDataTypes",
            columns=BUSCO,
            limit=2,
        ),
    )

    sent = json.loads(route.calls.last.request.content)
    assert sent["reportConfig"]["attributes"] == BUSCO
    assert (table.total_records, table.matched_rows, len(table.rows)) == (831, 5, 2)
    assert table.rows[0] == TableRow(
        record="Edhazardia aedis USNM 41457",
        values={
            "species": "Edhazardia aedis",
            "genecount": "4262",
            "busco_genome": ("C: 97.4%[S: 96.5%,D: 0.9%],F: 0.5%,M: 2.1%,n:425"),
            "busco_lineage_dataset": "microsporidia_odb12",
        },
    )
    assert "Showing 2 of 5 rows" in table.note
    assert "831" in table.note


async def test_contains_keeps_only_the_rows_that_name_it(wdk: respx.MockRouter) -> None:
    wdk.post(PORTAL_REPORT).mock(
        return_value=httpx.Response(
            200, json=recorded_body("veupathdb_genome_data_types_report.json")
        )
    )

    table = await read_search_table(
        "veupathdb",
        TableRequest(
            record_type="organism",
            search_name="GenomeDataTypes",
            columns=BUSCO,
            contains="aspergillus",
        ),
    )

    assert [row.values["species"] for row in table.rows] == [
        "Aspergillus luchuensis",
        "Aspergillus versicolor",
    ]


async def test_orthomcl_reads_its_proteome_table_row_by_row(
    wdk: respx.MockRouter,
) -> None:
    route = wdk.post(ORTHOMCL_REPORT).mock(
        return_value=httpx.Response(
            200, json=recorded_body("orthomcl_data_summary_report.json")
        )
    )

    table = await read_search_table(
        "orthomcl",
        TableRequest(
            record_type="helper",
            search_name="ByDefault",
            table="DataSummary",
            columns=["name", "sequences", "groups"],
        ),
    )

    sent = json.loads(route.calls.last.request.content)
    assert (sent["reportConfig"]["attributes"], sent["reportConfig"]["tables"]) == (
        [],
        ["DataSummary"],
    )
    assert table.matched_rows == 6
    assert table.note == "The search returned 1 record. Showing all 6 rows."
    assert table.rows[0].values == {
        "name": "Acanthamoeba castellanii str. Neff",
        "sequences": "14977",
        "groups": "7711",
    }


async def test_a_column_the_record_type_lacks_is_refused_with_near_names() -> None:
    with pytest.raises(UnreadableRecordError, match="busco_genome"):
        await read_search_table(
            "veupathdb",
            TableRequest(
                record_type="organism",
                search_name="GenomeDataTypes",
                columns=["busco_genomic"],
            ),
        )


async def test_a_search_of_another_record_type_is_refused() -> None:
    with pytest.raises(UnreadableRecordError, match="GenomeDataTypes"):
        await read_search_table(
            "veupathdb",
            TableRequest(
                record_type="organism",
                search_name="GenomeDataType",
            ),
        )


async def test_a_gene_search_is_refused_as_a_table() -> None:
    with pytest.raises(UnreadableRecordError, match="strategy step"):
        await read_search_table(
            "veupathdb",
            TableRequest(
                record_type="transcript",
                search_name="GenesByTaxon",
            ),
        )


async def test_a_refusal_from_wdk_names_the_parameter_it_needs(
    wdk: respx.MockRouter,
) -> None:
    wdk.post(PORTAL_REPORT).mock(
        return_value=httpx.Response(
            422,
            text=json.dumps(
                {
                    "level": "RUNNABLE",
                    "isValid": False,
                    "errors": {
                        "general": [],
                        "byKey": {"organism": ["Cannot be empty."]},
                    },
                }
            ),
        )
    )

    with pytest.raises(UnreadableRecordError, match="Cannot be empty"):
        await read_search_table(
            "veupathdb",
            TableRequest(
                record_type="organism",
                search_name="GenomeDataTypes",
            ),
        )


def _asked_records(route: respx.Route) -> int:
    return json.loads(route.calls.last.request.content)["reportConfig"]["pagination"][
        "numRecords"
    ]


async def test_a_read_asks_the_site_for_only_the_records_it_shows(
    wdk: respx.MockRouter,
) -> None:
    route = wdk.post(PORTAL_REPORT).mock(
        return_value=httpx.Response(
            200, json=recorded_body("veupathdb_genome_data_types_report.json")
        )
    )

    await read_search_table(
        "veupathdb",
        TableRequest(
            record_type="organism",
            search_name="GenomeDataTypes",
            columns=BUSCO,
            limit=2,
        ),
    )

    assert _asked_records(route) == 2


async def test_contains_scans_a_thousand_records_at_most(
    wdk: respx.MockRouter,
) -> None:
    route = wdk.post(PORTAL_REPORT).mock(
        return_value=httpx.Response(
            200, json=recorded_body("veupathdb_genome_data_types_report.json")
        )
    )

    await read_search_table(
        "veupathdb",
        TableRequest(
            record_type="organism",
            search_name="GenomeDataTypes",
            columns=BUSCO,
            contains="aspergillus",
        ),
    )

    assert _asked_records(route) == 1000


async def test_a_table_read_asks_for_no_more_records_than_rows_it_shows(
    wdk: respx.MockRouter,
) -> None:
    route = wdk.post(ORTHOMCL_REPORT).mock(
        return_value=httpx.Response(
            200, json=recorded_body("orthomcl_data_summary_report.json")
        )
    )

    await read_search_table(
        "orthomcl",
        TableRequest(
            record_type="helper",
            search_name="ByDefault",
            table="DataSummary",
            columns=["name", "sequences", "groups"],
            contains="falciparum",
            limit=20,
        ),
    )

    assert _asked_records(route) == 20

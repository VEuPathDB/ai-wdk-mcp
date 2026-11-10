from __future__ import annotations

import json
from collections.abc import Iterator

import httpx
import pytest
import respx
from tests._support.record_columns_site import recorded_body

from veupathdb_mcp.records import read_site_link

pytestmark = pytest.mark.usefixtures("catalog")

PORTAL = "https://qa.veupathdb.org/veupathdb.qa"
GENOMES = f"{PORTAL}/app/search/organism/GenomeDataTypes/result"


@pytest.fixture
def wdk() -> Iterator[respx.MockRouter]:
    with respx.mock(assert_all_called=False) as router:
        router.get(f"{PORTAL}/app").mock(return_value=httpx.Response(200))
        yield router


async def test_the_genome_page_is_read_as_its_table(wdk: respx.MockRouter) -> None:
    route = wdk.post(
        f"{PORTAL}/service/record-types/organism/searches/GenomeDataTypes"
        "/reports/standard"
    ).mock(
        return_value=httpx.Response(
            200, json=recorded_body("veupathdb_genome_data_types_report.json")
        )
    )

    reading = await read_site_link(GENOMES)

    sent = json.loads(route.calls.last.request.content)
    assert sent["searchConfig"]["parameters"] == {}
    assert (reading.site_id, reading.kind) == ("veupathdb", "search_result")
    assert reading.summary.startswith(
        "The link runs GenomeDataTypes on veupathdb with no parameter values in "
        "the link. It shows Organisms: Genome Info and Stats."
    )
    assert reading.table is not None
    assert reading.table.rows[0].record == "Edhazardia aedis USNM 41457"


async def test_a_gene_result_is_named_a_strategy_step() -> None:
    reading = await read_site_link(
        f"{PORTAL}/app/search/transcript/GenesByTaxon/result"
        "?param.organism=Plasmodium+falciparum+3D7"
    )

    assert (reading.kind, reading.table) == ("search_result", None)
    assert reading.summary == (
        "The link runs GenesByTaxon on veupathdb with organism = Plasmodium "
        "falciparum 3D7. It shows Organism, a gene result. A gene result is built "
        "as a strategy step, not read as a table."
    )


async def test_a_search_the_site_lacks_names_the_nearest_it_has() -> None:
    reading = await read_site_link(
        f"{PORTAL}/app/search/organism/GenomeDataType/result"
    )

    assert "has no search 'GenomeDataType'" in reading.summary
    assert "GenomeDataTypes" in reading.summary


async def test_a_strategy_link_says_whose_account_holds_it() -> None:
    reading = await read_site_link(
        f"{PORTAL}/app/workspace/strategies/214670300/227351670"
    )

    assert reading.kind == "strategy"
    assert reading.summary.startswith(
        "The link opens strategy 214670300, open at step 227351670 on veupathdb."
    )
    assert "share link" in reading.summary


async def test_a_link_to_no_configured_site_reads_nothing() -> None:
    reading = await read_site_link("https://example.org/app/search/a/b/result")

    assert (reading.site_id, reading.kind, reading.table) == (None, "outside", None)

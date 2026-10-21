import httpx
import pytest
from fastmcp.exceptions import ToolError
from tests._support.busco import NF135, served_organisms
from tests._support.wdk_genes import ReportSite, answer_of
from veupathdb.errors import WDKLoginRequiredError
from veupathdb.wdk import WDKAnswer

from veupathdb_mcp.audit import genes
from veupathdb_mcp.tools.audit_busco_tools import audit_genome_priority


class FailingSite(ReportSite):
    def __init__(self, error: Exception) -> None:
        super().__init__([])
        self.error = error

    async def run_search_report(self, *args: object, **kwargs: object) -> WDKAnswer:
        raise self.error


def serve(monkeypatch: pytest.MonkeyPatch, site: ReportSite) -> None:
    monkeypatch.setattr(genes, "get_wdk_client", lambda site_id: site)


async def test_the_tool_ranks_the_site_genomes_by_gap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    serve(monkeypatch, ReportSite([answer_of(served_organisms())]))

    result = await audit_genome_priority("plasmodb")
    ranked = result.genomes

    assert (result.site_id, len(ranked)) == ("plasmodb", 63)
    assert ranked[0].gap == 27.0
    assert list(result.model_dump(by_alias=True)) == ["siteId", "genomes"]
    nf135 = next(p for p in ranked if p.organism == NF135)
    assert (nf135.protein.complete, nf135.genome.complete, nf135.gap) == (
        93.0,
        98.4,
        5.4,
    )


async def test_a_site_refusal_is_a_tool_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    serve(monkeypatch, FailingSite(WDKLoginRequiredError()))

    with pytest.raises(ToolError, match="registered"):
        await audit_genome_priority("plasmodb")


async def test_a_site_that_does_not_answer_is_a_tool_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    serve(monkeypatch, FailingSite(httpx.ConnectTimeout("slow")))

    with pytest.raises(
        ToolError, match="plasmodb did not answer the audit reads: ConnectTimeout"
    ):
        await audit_genome_priority("plasmodb")


async def test_an_unreadable_record_is_a_tool_error_naming_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = [
        {
            **record,
            "attributes": {
                "organism_full": NF135,
                "busco_protein": "C: ninety",
                "busco_genome": None,
                "busco_lineage_dataset": "aconoidasida_odb12",
            },
        }
        if record["displayName"] == "<i>Plasmodium falciparum</i> NF135.C10"
        else record
        for record in served_organisms()
    ]
    serve(monkeypatch, ReportSite([answer_of(records)]))

    with pytest.raises(ToolError, match=r"source_id=TMPTX_pfalNF135C10.*busco_protein"):
        await audit_genome_priority("plasmodb")

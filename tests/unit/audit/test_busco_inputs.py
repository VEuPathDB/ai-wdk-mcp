import pytest
from tests._support.busco import NF135, served_organisms
from tests._support.wdk_genes import ReportSite, answer_of
from veupathdb.errors import DataParsingError
from veupathdb.wdk import WDKSearchConfig

from veupathdb_mcp.audit import genes
from veupathdb_mcp.audit.busco import BUSCO_ATTRIBUTES
from veupathdb_mcp.audit.busco_inputs import genome_priorities
from veupathdb_mcp.audit.genes import organism_report


def serve(monkeypatch: pytest.MonkeyPatch, site: ReportSite) -> ReportSite:
    monkeypatch.setattr(genes, "get_wdk_client", lambda site_id: site)
    return site


async def test_the_organism_report_reads_genome_data_types_without_parameters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = served_organisms()
    site = serve(monkeypatch, ReportSite([answer_of(records)]))

    answer = await organism_report("plasmodb", BUSCO_ATTRIBUTES)

    assert len(answer.records) == 64
    assert site.searches == [
        (
            "organism",
            "GenomeDataTypes",
            WDKSearchConfig(parameters={}),
            {
                "attributes": [
                    "organism_full",
                    "busco_protein",
                    "busco_genome",
                    "busco_lineage_dataset",
                ],
                "tables": [],
                "pagination": {"offset": 0, "numRecords": 2000},
            },
        )
    ]
    assert BUSCO_ATTRIBUTES == (
        "organism_full",
        "busco_protein",
        "busco_genome",
        "busco_lineage_dataset",
    )


async def test_a_truncated_organism_report_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    serve(monkeypatch, ReportSite([answer_of(served_organisms()[:10], total=64)]))

    with pytest.raises(
        DataParsingError, match="GenomeDataTypes report served 10 records"
    ):
        await organism_report("plasmodb", BUSCO_ATTRIBUTES)


async def test_the_genome_priorities_of_plasmodb_rank_nf135_above_nf166(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    serve(monkeypatch, ReportSite([answer_of(served_organisms())]))

    ranked = await genome_priorities("plasmodb")

    gaps = {priority.organism: priority.gap for priority in ranked}
    assert gaps[NF135] == 5.4
    assert gaps["Plasmodium falciparum NF166"] == 2.3
    assert [p.gap for p in ranked] == sorted((p.gap for p in ranked), reverse=True)

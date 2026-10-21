import pytest
from fastmcp.exceptions import ToolError
from tests._support.audit_site import own_id
from tests._support.evidence_site import (
    K13,
    NF54,
    PIGA,
    EvidenceSite,
    declared,
    gene_record,
    genome_answer,
)
from veupathdb.errors import DataParsingError, VEuPathDBErrorCode
from veupathdb.wdk import WDKAnswer, WDKRecordInstance

from veupathdb_mcp.audit.evidence import GenomeProvenance, requested_tables
from veupathdb_mcp.audit.evidence_inputs import (
    GENOME_ATTRIBUTES,
    declared_tables,
    gene_evidence,
    genome_provenance,
)
from veupathdb_mcp.audit.genes import ORGANISM_SEARCH, organism_report
from veupathdb_mcp.tool_errors import tool_error
from veupathdb_mcp.tools.refusals import payload_or_error
from veupathdb_mcp.wdk.gene_record_type import GENE_RECORD_TYPE_PATH


async def test_the_declared_tables_are_read_from_the_gene_record_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = EvidenceSite(monkeypatch, "plasmodb")

    names = await declared_tables("plasmodb")

    assert site.gets == [GENE_RECORD_TYPE_PATH]
    assert len(names) == 75
    assert names[:3] == [
        "SubcellularLocationGeneLists",
        "WolfPsortForm",
        "BlastpForm",
    ]
    assert "pfal3D7_phenotype_pB_mutagenesis_MIS_MFS_RSRC" in names


async def test_a_record_type_without_tables_is_a_parsing_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = EvidenceSite(monkeypatch, "plasmodb")
    site.record_type = {"urlSegment": "gene"}

    with pytest.raises(DataParsingError, match="the gene record type of plasmodb"):
        await declared_tables("plasmodb")


async def test_the_genome_report_reads_every_organism_record_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = EvidenceSite(monkeypatch, "plasmodb")

    answer = await organism_report("plasmodb", GENOME_ATTRIBUTES)

    assert len(answer.records) == 64
    [(record_type, search, config, report)] = site.reports
    assert (record_type, search, config.parameters) == ("organism", ORGANISM_SEARCH, {})
    assert report["attributes"] == list(GENOME_ATTRIBUTES)


async def test_a_truncated_genome_report_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = EvidenceSite(monkeypatch, "plasmodb")
    site.answer = genome_answer(total=65)

    with pytest.raises(DataParsingError, match="served 64 records of a total of 65"):
        await organism_report("plasmodb", GENOME_ATTRIBUTES)


async def test_gene_evidence_reads_the_record_type_and_the_gene_record_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = EvidenceSite(monkeypatch, "plasmodb")
    site.records[K13] = gene_record("evidence_pfal3D7_k13.json")

    evidence = payload_or_error(await gene_evidence("plasmodb", K13))

    assert site.gets == [GENE_RECORD_TYPE_PATH]
    [(site_id, gene, attributes, tables)] = site.record_reads
    assert (site_id, gene, attributes) == ("plasmodb", K13, ["organismAbbrev"])
    assert tables == requested_tables(declared("plasmodb"))
    assert (evidence.gene, len(evidence.peptides), evidence.pubmed) == (K13, 59, 44)
    assert evidence.gene_ids == [own_id(K13)]


async def test_an_unreadable_evidence_table_is_a_parsing_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = EvidenceSite(monkeypatch, "plasmodb")
    site.records[PIGA] = WDKRecordInstance.model_validate(
        {"tables": {"MassSpecDownload": [{"sequence": "MK", "protein_start": "x"}]}}
    )

    with pytest.raises(
        DataParsingError,
        match=(
            f"the gene record of {PIGA} on plasmodb serves unreadable "
            "evidence: MassSpecDownload$"
        ),
    ):
        await gene_evidence("plasmodb", PIGA)


async def test_an_unreadable_screen_cell_names_its_screen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = EvidenceSite(monkeypatch, "plasmodb")
    site.records[PIGA] = WDKRecordInstance.model_validate(
        {
            "attributes": {"organismAbbrev": "pfal3D7"},
            "tables": {"PhenotypeScore": [{"score": 0.5}]},
        }
    )

    with pytest.raises(
        DataParsingError,
        match=(
            f"the gene record of {PIGA} on plasmodb serves unreadable "
            "evidence: PhenotypeScore$"
        ),
    ):
        await gene_evidence("plasmodb", PIGA)


async def test_genome_provenance_names_the_organism_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    EvidenceSite(monkeypatch, "plasmodb")

    provenance = await genome_provenance("plasmodb", NF54)

    assert isinstance(provenance, GenomeProvenance)
    assert (provenance.record_id, provenance.genome_version) == (
        "NCBITAXON_5843",
        "GCA_009761475.1",
    )


async def test_an_organism_the_site_does_not_hold_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    EvidenceSite(monkeypatch, "plasmodb")

    refusal = await genome_provenance("plasmodb", "Plasmodium falciparum NF55")

    assert refusal == tool_error(
        VEuPathDBErrorCode.VALIDATION_ERROR,
        "Plasmodium falciparum NF55 names no genome of plasmodb",
    )


async def test_an_unreadable_organism_record_is_a_parsing_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = EvidenceSite(monkeypatch, "plasmodb")
    site.answer = WDKAnswer.model_validate(
        {
            "meta": {"totalCount": 1},
            "records": [{"attributes": {"organism_full": NF54}}],
        }
    )

    with pytest.raises(
        DataParsingError,
        match=f"the organism record of {NF54} on plasmodb is not readable",
    ):
        await genome_provenance("plasmodb", NF54)


async def test_the_declared_tables_are_read_once_per_site(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = EvidenceSite(monkeypatch, "plasmodb")
    site.records[K13] = gene_record("evidence_pfal3D7_k13.json")
    site.records[PIGA] = gene_record("evidence_pfal3D7_piga.json")

    await gene_evidence("plasmodb", K13)
    await gene_evidence("plasmodb", PIGA)
    await declared_tables("tritrypdb")

    assert site.gets == [GENE_RECORD_TYPE_PATH, GENE_RECORD_TYPE_PATH]
    assert [read[1] for read in site.record_reads] == [K13, PIGA]


async def test_an_id_the_site_resolves_to_no_gene_reads_no_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = EvidenceSite(monkeypatch, "plasmodb")

    with pytest.raises(ToolError, match=r"^PF3D7_9 names no gene of plasmodb$"):
        payload_or_error(await gene_evidence("plasmodb", "PF3D7_9"))

    assert (site.gets, site.record_reads) == ([], [])

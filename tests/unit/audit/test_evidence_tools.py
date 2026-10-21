import httpx
import pytest
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.tools import Tool
from tests._support.evidence_site import (
    K13,
    NF54,
    EvidenceSite,
    gene_record,
)
from veupathdb.errors import WDKError

from veupathdb_mcp.audit.evidence import GeneEvidence, GenomeProvenance
from veupathdb_mcp.tools import audit_evidence_tools
from veupathdb_mcp.tools.audit_evidence_tools import audit_genome_provenance


async def test_the_evidence_tool_returns_what_the_gene_record_serves(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = EvidenceSite(monkeypatch, "plasmodb")
    site.records[K13] = gene_record("evidence_pfal3D7_k13.json")

    evidence = await audit_evidence_tools.audit_gene_evidence("plasmodb", K13)

    assert (evidence.gene, evidence.comments, evidence.pubmed) == (K13, 9, 44)
    assert [hit.pdb_id for hit in evidence.pdb_hits][:2] == ["4zgc", "4yy8"]
    assert len(site.record_reads) == 1


async def test_the_provenance_tool_returns_the_organism_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = EvidenceSite(monkeypatch, "plasmodb")

    provenance = await audit_evidence_tools.audit_genome_provenance("plasmodb", NF54)

    assert (provenance.organism, provenance.genome_source) == (NF54, "INSDC")
    assert provenance.annotation_source is None
    assert len(site.reports) == 1


async def test_an_organism_the_site_does_not_hold_is_a_tool_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    EvidenceSite(monkeypatch, "plasmodb")

    with pytest.raises(ToolError, match="Plasmodium vivax X names no genome"):
        await audit_evidence_tools.audit_genome_provenance(
            "plasmodb", "Plasmodium vivax X"
        )


async def test_a_site_error_is_a_tool_error(monkeypatch: pytest.MonkeyPatch) -> None:
    async def refused(site_id: str, gene: str) -> GeneEvidence:
        msg = "the gene record of NOT_A_GENE was not found"
        raise WDKError(msg)

    monkeypatch.setattr(audit_evidence_tools, "gene_evidence", refused)

    with pytest.raises(ToolError, match="the gene record of NOT_A_GENE was not found"):
        await audit_evidence_tools.audit_gene_evidence("plasmodb", "NOT_A_GENE")


async def test_a_site_that_does_not_answer_is_a_tool_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def silent(site_id: str, gene: str) -> GeneEvidence:
        msg = "timed out"
        raise httpx.ConnectTimeout(msg)

    monkeypatch.setattr(audit_evidence_tools, "gene_evidence", silent)

    with pytest.raises(ToolError, match="plasmodb did not answer the audit reads"):
        await audit_evidence_tools.audit_gene_evidence("plasmodb", K13)


async def test_the_evidence_is_served_in_camel_case_over_mcp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = EvidenceSite(monkeypatch, "plasmodb")
    site.records[K13] = gene_record("evidence_pfal3D7_k13.json")
    server = FastMCP("evidence")
    server.tool(audit_evidence_tools.audit_gene_evidence)

    async with Client(server) as client:
        result = await client.call_tool(
            "audit_gene_evidence", {"site_id": "plasmodb", "gene": K13}
        )

    served = result.structured_content
    assert served is not None
    assert served["pdbHits"][0]["pdbId"] == "4zgc"
    assert served["peptides"][0]["experiments"] == [
        "Blood stage phospho- and total proteome (3D7)"
    ]
    assert served["phenotypes"] == [
        {"table": "pfal3D7_phenotype_pB_mutagenesis_MIS_MFS_RSRC", "rows": []}
    ]
    assert served["unprefixedTables"][0]["table"] == "EdaPhenotypeGraphsDataTable"
    assert served["pdbHits"][0]["proteinCoveredPercent"] == 0


def test_the_evidence_description_warns_that_zero_coverage_is_served() -> None:
    tool = Tool.from_function(audit_evidence_tools.audit_gene_evidence)

    assert tool.description is not None
    words = " ".join(tool.description.split())
    assert "the site serves 0 for some near-identical hits" in words
    assert "so 0 does not mean no overlap" in words
    assert "at most 20 rows per transcript" in words
    assert (
        "table with no row does not mean the screen has no result for the gene" in words
    )
    assert "named for no organism and offered on every organism of the site" in words


def test_the_provenance_description_names_every_served_field() -> None:
    words = " ".join((audit_genome_provenance.__doc__ or "").split())

    named = [
        field in words
        for field in GenomeProvenance.model_json_schema(mode="serialization")[
            "properties"
        ]
    ]

    assert named == [True] * len(named)

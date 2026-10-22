import json
from pathlib import Path

import pytest
from pydantic import JsonValue, TypeAdapter
from tests._support.audit_site import reads_for
from tests._support.proteins import row
from veupathdb import JSONObject
from veupathdb.wdk import WDKAnswer, WDKRecordInstance, WDKSearchConfig

from veupathdb_mcp.audit import evidence_inputs, genes, served
from veupathdb_mcp.audit.gene_ids import GeneReads
from veupathdb_mcp.audit.genes import GeneRow
from veupathdb_mcp.wdk import gene_record_type
from veupathdb_mcp.wdk.gene_record_type import GeneRecordType
from veupathdb_mcp.wdk.site_cache import SiteCache

FIXTURES = Path(__file__).resolve().parents[1] / "unit/audit/fixtures"
PIGA = "PF3D7_1032400"
K13 = "PF3D7_1343700"
DMAW = "Afu2g18040"
GLO1 = "LmjF.35.3010"
NF54 = "Plasmodium falciparum NF54"
_RECORDS: TypeAdapter[list[JsonValue]] = TypeAdapter(list[JsonValue])


def recorded(name: str) -> JsonValue:
    body: JsonValue = json.loads((FIXTURES / name).read_text())
    return body


def declared(site: str) -> list[str]:
    served_type = recorded(f"evidence_{site}_tables.json")
    names = GeneRecordType.model_validate(served_type).names
    assert names is not None
    return names


def gene_record(name: str) -> WDKRecordInstance:
    return WDKRecordInstance.model_validate(recorded(name))


def genome_answer(total: int | None = None) -> WDKAnswer:
    records = _RECORDS.validate_python(recorded("evidence_plasmodb_genomes.json"))
    return WDKAnswer.model_validate(
        {
            "records": records,
            "meta": {"totalCount": len(records) if total is None else total},
        }
    )


class EvidenceSite:
    def __init__(self, monkeypatch: pytest.MonkeyPatch, site: str) -> None:
        self.record_type: JsonValue = recorded(f"evidence_{site}_tables.json")
        self.records: dict[str, WDKRecordInstance] = {}
        self.answer = genome_answer()
        self.gets: list[str] = []
        self.record_reads: list[tuple[str, str, list[str], list[str]]] = []
        self.reports: list[tuple[str, str, WDKSearchConfig, JSONObject]] = []
        monkeypatch.setattr(gene_record_type, "_SERVED", SiteCache())
        monkeypatch.setattr(gene_record_type, "get_wdk_client", lambda site_id: self)
        monkeypatch.setattr(genes, "get_wdk_client", lambda site_id: self)
        monkeypatch.setattr(evidence_inputs, "gene_record", self.gene_record)
        monkeypatch.setattr(served, "rows_named", self.rows_named)

    async def gene_rows(self, site_id: str, gene_ids: list[str]) -> list[GeneRow]:
        return [row(gene, site_id, None) for gene in gene_ids if gene in self.records]

    async def rows_named(self, site_id: str, gene_ids: list[str]) -> GeneReads:
        return reads_for(await self.gene_rows(site_id, gene_ids), gene_ids, {}, {})

    async def genes_by_text(self, site_id: str, gene_id: str) -> list[GeneRow]:
        return []

    async def get(self, path: str) -> JsonValue:
        self.gets.append(path)
        return self.record_type

    async def gene_record(
        self, site_id: str, gene: str, attributes: list[str], tables: list[str]
    ) -> WDKRecordInstance:
        self.record_reads.append((site_id, gene, attributes, tables))
        return self.records[gene]

    async def run_search_report(
        self,
        record_type: str,
        search_name: str,
        config: WDKSearchConfig,
        report: JSONObject,
    ) -> WDKAnswer:
        self.reports.append((record_type, search_name, config, report))
        return self.answer

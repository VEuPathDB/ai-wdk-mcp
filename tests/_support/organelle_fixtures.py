import json
from collections.abc import Sequence
from pathlib import Path

import pytest
from scripts.record_audit_organelle import ContigRecording, GeneRecording
from tests._support.audit_site import AuditSite, Contig
from veupathdb import JSONObject
from veupathdb.wdk import WDKAnswer, WDKRecordInstance, WDKSearchConfig

from veupathdb_mcp.audit import gene_ids, gene_models, genes, organelle_inputs, served
from veupathdb_mcp.audit.genes import GeneRow

FIXTURES = Path(__file__).resolve().parents[1] / "unit/audit/fixtures"
CYTB = "PF3D7_MIT02300"
RECORDED = ("pfal3D7", "pfalNF54", "pfalSN01", "pfal7G8", "pfal7G82019")


def contig(name: str) -> ContigRecording:
    path = FIXTURES / f"organelle_{name}_mito.json"
    return ContigRecording.model_validate_json(path.read_text())


def cytb() -> GeneRecording:
    path = FIXTURES / "organelle_pfal3D7_cytb.json"
    return GeneRecording.model_validate_json(path.read_text())


def _serve_cytb(monkeypatch: pytest.MonkeyPatch) -> None:
    recording = cytb()

    async def answers(
        site_id: str, gene_ids: list[str], attributes: Sequence[str]
    ) -> list[WDKAnswer]:
        assert (site_id, gene_ids) == ("plasmodb", [recording.gene])
        return [WDKAnswer.model_validate(recording.report)]

    monkeypatch.setattr(genes, "locus_tag_answers", answers)
    monkeypatch.setattr(gene_ids, "locus_tag_answers", answers)


async def cytb_protein(monkeypatch: pytest.MonkeyPatch) -> str:
    _serve_cytb(monkeypatch)
    return (await genes.proteins_of("plasmodb", [CYTB]))[CYTB]


class GenomeReports:
    def __init__(self, recordings: list[ContigRecording]) -> None:
        self.recordings = recordings
        self.organisms: list[str] = []

    async def run_search_report(
        self,
        record_type: str,
        search_name: str,
        search_config: WDKSearchConfig,
        report_config: JSONObject | None = None,
    ) -> WDKAnswer:
        [organism] = json.loads(search_config.parameters["organism"])
        self.organisms.append(organism)
        records = [
            record
            for recorded in self.recordings
            if recorded.organism == organism
            for record in recorded.genes
        ]
        return WDKAnswer.model_validate(
            {
                "meta": {"totalCount": len(records), "responseCount": len(records)},
                "records": records,
            }
        )


def organelle_site(monkeypatch: pytest.MonkeyPatch) -> AuditSite:
    site = AuditSite(monkeypatch)

    async def genes_of_genome(site_id: str, organism: str) -> list[GeneRow]:
        return [row for row in site.rows if row.organism == organism]

    monkeypatch.setattr(organelle_inputs, "gene_model", site.gene_model)
    monkeypatch.setattr(organelle_inputs, "gene_organism", site.gene_organism)
    monkeypatch.setattr(organelle_inputs, "genes_of_genome", genes_of_genome)
    monkeypatch.setattr(organelle_inputs, "get_jbrowse_client", lambda site_id: site)
    monkeypatch.setattr(organelle_inputs, "GenomeReader", site.reader)
    return site


def recorded_site(monkeypatch: pytest.MonkeyPatch) -> tuple[AuditSite, GenomeReports]:
    site = organelle_site(monkeypatch)
    recordings = [contig(name) for name in RECORDED]
    records = {
        WDKRecordInstance.model_validate(r.record).id[0].value: r.record
        for r in recordings
    } | {CYTB: cytb().record}
    reports = GenomeReports(recordings)

    async def record(
        site_id: str, gene: str, attributes: list[str], tables: list[str]
    ) -> WDKRecordInstance:
        assert site_id == "plasmodb"
        site.models_read.append(gene)
        return WDKRecordInstance.model_validate(records[gene])

    _serve_cytb(monkeypatch)
    monkeypatch.setattr(gene_models, "gene_record", record)
    monkeypatch.setattr(genes, "get_wdk_client", lambda site_id: reports)
    monkeypatch.setattr(served, "rows_named", gene_ids.rows_named)
    monkeypatch.setattr(served, "proteins_of", genes.proteins_of)
    monkeypatch.setattr(organelle_inputs, "gene_model", gene_models.gene_model)
    monkeypatch.setattr(organelle_inputs, "gene_organism", gene_models.gene_organism)
    monkeypatch.setattr(organelle_inputs, "genes_of_genome", genes.genes_of_genome)
    for recorded in recordings:
        site.contigs[recorded.abbrev, recorded.seqid] = Contig.whole(recorded.sequence)
    return site, reports

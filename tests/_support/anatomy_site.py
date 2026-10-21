from pathlib import Path

import pytest
from pydantic import BaseModel, ConfigDict
from scripts.record_audit_anatomy import AnatomyRecording
from scripts.record_audit_fixtures import GeneLocation
from tests._support.audit_site import AuditSite, Contig
from veupathdb.wdk import WDKRecordInstance

from veupathdb_mcp.audit import anatomy_inputs, gene_models
from veupathdb_mcp.audit.gene_models import GeneModel
from veupathdb_mcp.audit.genes import GeneRow

FIXTURES = Path(__file__).resolve().parents[1] / "unit/audit/fixtures"
NF54_PIGA = "PfNF54_100037200:pseudogene"
PIGA = "PF3D7_1032400"
NF54_PAGM = "PfNF54_110034300:pseudogene"
PAGM = "PF3D7_1130000"
PIGA_FILE = "anatomy_pfalNF54_piga.json"
PAGM_FILE = "anatomy_pfalNF54_pagm.json"


def recording(name: str) -> AnatomyRecording:
    return AnatomyRecording.model_validate_json((FIXTURES / name).read_text())


class RecordedOrganism(BaseModel):
    model_config = ConfigDict(extra="ignore")

    organism_full: str


def location_only_row(gene: str, record: WDKRecordInstance, pseudo: bool) -> GeneRow:
    place = GeneLocation.model_validate(record.attributes)
    return GeneRow(
        gene=gene,
        organism=RecordedOrganism.model_validate(record.attributes).organism_full,
        ortholog_group="",
        protein_length=None,
        name="",
        product="",
        sequence_id=place.sequence_id,
        start=place.start_min,
        end=place.end_max,
        strand=place.strand_plus_minus,
        pseudo=pseudo,
        gene_type="",
    )


class AnatomySite(AuditSite):
    def __init__(self, monkeypatch: pytest.MonkeyPatch, name: str) -> None:
        super().__init__(monkeypatch)
        recorded = recording(name)
        self.records = {
            gene: WDKRecordInstance.model_validate(raw)
            for gene, raw in recorded.records.items()
        }
        self.record_asks: list[tuple[str, list[str], list[str]]] = []
        for gene, record in self.records.items():
            pseudo = gene == recorded.strain_gene
            self.rows.append(location_only_row(gene, record, pseudo))
            self.models[gene] = GeneModel.from_record(record)
        reference, strain = recorded.windows
        abbrev = self.models[recorded.reference_gene].organism_abbrev
        self.regions[abbrev, reference.seqid, reference.start, reference.end] = (
            reference.sequence
        )
        abbrev = self.models[recorded.strain_gene].organism_abbrev
        self.contigs[abbrev, strain.seqid] = Contig(
            start=strain.start,
            sequence=strain.sequence,
            length=recorded.contig_length,
        )
        monkeypatch.setattr(gene_models, "gene_record", self.gene_record)
        monkeypatch.setattr(anatomy_inputs, "get_jbrowse_client", lambda site_id: self)
        monkeypatch.setattr(anatomy_inputs, "GenomeReader", self.reader)

    async def gene_record(
        self, site_id: str, gene: str, attributes: list[str], tables: list[str]
    ) -> WDKRecordInstance:
        self.record_asks.append((gene, attributes, tables))
        return self.records[gene]

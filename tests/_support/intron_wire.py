from pathlib import Path

import pytest
from scripts.record_audit_introns import IntronWire
from tests._support.audit_wire import ServedRecords
from tests._support.intron_site import JBrowse
from tests._support.record_site import load_records, transcript_proteins
from tests._support.row_reads import serve_recorded_rows
from tests._support.wdk_genes import ReportSite, serve_private
from veupathdb.jbrowse import GenomeWindow
from veupathdb.wdk import WDKRecordInstance

from veupathdb_mcp.audit import gene_models

FIXTURES = Path(__file__).resolve().parents[1] / "unit/audit/fixtures"


def load_introns(name: str) -> IntronWire:
    return IntronWire.model_validate_json((FIXTURES / name).read_text())


class Served:
    def __init__(
        self, monkeypatch: pytest.MonkeyPatch, wire: IntronWire, proteins: str
    ) -> None:
        self.records = ServedRecords(
            [
                WDKRecordInstance.model_validate(wire.model_record),
                WDKRecordInstance.model_validate(wire.ortholog_record),
            ]
        )
        monkeypatch.setattr(gene_models, "get_strategy_api", lambda site: self.records)
        self.reports: ReportSite = serve_private(monkeypatch, [])[1]
        self.rows = serve_recorded_rows(
            monkeypatch,
            wire.gene_answers,
            [*wire.protein_answers, *wire.ortholog_protein_answers],
            transcript_proteins(load_records(proteins)),
        )
        self.jbrowse = JBrowse(
            monkeypatch,
            wire.junction_tracks,
            {
                (path, wire.junction_seqid): lines
                for path, lines in wire.junction_lines.items()
            },
            GenomeWindow(
                seqid=wire.junction_seqid, start=wire.window_start, sequence=wire.window
            ),
        )

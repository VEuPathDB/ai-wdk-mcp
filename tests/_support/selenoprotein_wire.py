import pytest
from scripts.record_audit_records import RecordWire
from scripts.record_audit_selenoprotein import FILE
from tests._support.record_site import (
    RecordedRecords,
    ReplayStore,
    install_recorded_records,
    load_records,
)
from tests._support.wdk_genes import ReportSite, serve_private
from veupathdb.jbrowse import GenomeReader, JBrowseClient
from veupathdb.wdk import get_site

from veupathdb_mcp.audit import served


class SelenoproteinWire:
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.wire: RecordWire = load_records(FILE)
        self.records: RecordedRecords = install_recorded_records(monkeypatch, self.wire)
        self.store = ReplayStore(self.wire.store)
        client = JBrowseClient(
            base_url=get_site(self.wire.site).web_base_url, transport=self.store
        )
        monkeypatch.setattr(served, "get_jbrowse_client", lambda site_id: client)
        monkeypatch.setattr(served, "GenomeReader", GenomeReader)
        self.reports: ReportSite = serve_private(monkeypatch, [])[1]

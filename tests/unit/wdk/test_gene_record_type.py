import pytest
from pydantic import JsonValue
from veupathdb.errors import DataParsingError
from veupathdb.testing.wdk_fixtures import load_recorded

from veupathdb_mcp.audit.evidence_inputs import declared_tables
from veupathdb_mcp.wdk import gene_record_type
from veupathdb_mcp.wdk.gene_record_type import GENE_RECORD_TYPE_PATH
from veupathdb_mcp.wdk.site_cache import SiteCache


class RecordTypeSite:
    def __init__(self, monkeypatch: pytest.MonkeyPatch, body: JsonValue) -> None:
        self.body = body
        self.gets: list[str] = []
        monkeypatch.setattr(gene_record_type, "_SERVED", SiteCache())
        monkeypatch.setattr(gene_record_type, "get_wdk_client", lambda site_id: self)

    async def get(self, path: str) -> JsonValue:
        self.gets.append(path)
        return self.body


async def test_one_recorded_record_type_serves_both_readers_from_one_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = RecordTypeSite(monkeypatch, load_recorded("record_type_build").json_body())

    served = await gene_record_type.gene_record_type("plasmodb")
    tables = await declared_tables("plasmodb")

    assert served.primary_key_column_refs == ["build_number"]
    assert tables == ["Datasets"]
    assert site.gets == [GENE_RECORD_TYPE_PATH]


async def test_an_unreadable_record_type_is_a_parsing_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    RecordTypeSite(monkeypatch, {"tables": "Datasets"})

    with pytest.raises(DataParsingError, match="record type of plasmodb is not"):
        await gene_record_type.gene_record_type("plasmodb")

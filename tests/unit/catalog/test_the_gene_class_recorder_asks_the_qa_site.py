from pathlib import Path

import httpx
import pytest
import respx
from scripts import record_orthomcl_gene_class
from scripts.record_orthomcl_gene_class import FILE, GENE, GeneClassWire
from veupathdb import VEuPathDBSettings, use_veupathdb_settings_source

QA_SERVICE = "https://qa.orthomcl.org/orthomcl.qa/service"
LISTED = ["group", "sequence"]


@respx.mock
async def test_the_recorder_sends_two_requests_to_the_qa_site(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sites = tmp_path / "sites.yaml"
    sites.write_text(
        "sites:\n"
        "  orthomcl:\n"
        "    base_url: https://demodb.example/demo/service\n"
        "    project_id: OrthoMCL\n"
    )
    installed = VEuPathDBSettings(veupathdb_sites_config=str(sites))
    use_veupathdb_settings_source(lambda: installed)
    monkeypatch.setenv("WDK_TEST_TOKEN", "test.account.token")
    listed = respx.get(f"{QA_SERVICE}/record-types").mock(
        return_value=httpx.Response(200, json=LISTED)
    )
    read = respx.post(f"{QA_SERVICE}/record-types/gene/records").mock(
        return_value=httpx.Response(404, text="no such record type")
    )

    written = await record_orthomcl_gene_class.record(tmp_path)

    wire = GeneClassWire.model_validate_json(written.read_text())
    assert written == tmp_path / FILE
    assert (listed.call_count, read.call_count, len(respx.calls)) == (1, 1, 2)
    assert (wire.record_types.response_json, wire.gene_record.status) == (LISTED, 404)
    assert wire.gene_record.request_json == {
        "primaryKey": [
            {"name": "source_id", "value": GENE},
            {"name": "project_id", "value": "OrthoMCL"},
        ],
        "attributes": [],
        "tables": [],
    }

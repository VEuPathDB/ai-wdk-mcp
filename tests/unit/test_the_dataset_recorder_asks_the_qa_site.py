from pathlib import Path

import httpx
import pytest
import respx
from scripts import record_all_datasets
from veupathdb import VEuPathDBSettings, use_veupathdb_settings_source

from veupathdb_mcp.catalog.catalog_metadata import DATASET_REPORT_PATH

QA_REPORT = f"https://qa.plasmodb.org/plasmo.qa/service{DATASET_REPORT_PATH}"


@respx.mock
async def test_a_recording_asks_the_qa_site_whatever_the_process_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sites = tmp_path / "sites.yaml"
    sites.write_text(
        "sites:\n"
        "  plasmodb:\n"
        "    base_url: https://demodb.example/demo/service\n"
        "    project_id: PlasmoDB\n"
    )
    installed = VEuPathDBSettings(veupathdb_sites_config=str(sites))
    use_veupathdb_settings_source(lambda: installed)
    store = tmp_path / "fixtures"
    monkeypatch.setattr(record_all_datasets, "_FIXTURES", store)
    route = respx.post(QA_REPORT).mock(
        return_value=httpx.Response(200, json={"records": []})
    )

    written = await record_all_datasets.record("plasmodb")

    assert route.called
    assert written == store / "plasmodb_all_datasets.json"
    assert QA_REPORT in written.read_text()

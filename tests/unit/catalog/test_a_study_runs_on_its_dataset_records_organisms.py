"""A study runs on the organisms of the dataset record it is, read from the
catalog the build already posts, and a study the site publishes no record for
runs on none."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from tests._support.recorded_catalog import recorded_catalog
from tests._support.recordings import TEST_ROOT
from veupathdb.testing import NEEDS_QA_RECORDING, needs_qa_recording

from veupathdb_mcp import catalog
from veupathdb_mcp.catalog import searches
from veupathdb_mcp.catalog.discovery import SearchCatalog


@pytest.mark.skipif(
    needs_qa_recording(TEST_ROOT / "unit/catalog/fixtures/plasmodb_all_datasets.json"),
    reason=NEEDS_QA_RECORDING,
)
async def test_a_study_runs_on_the_organisms_of_its_dataset_record(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    plasmodb = await recorded_catalog(monkeypatch, tmp_path, "plasmodb")

    assert [
        plasmodb.study_organisms(dataset_id)
        for dataset_id in ("DS_eeca6a5476", "DS_10068cde24", "DS_0000000000")
    ] == [["Plasmodium falciparum 3D7"], ["Plasmodium knowlesi strain A1H1"], []]


def test_a_host_reads_it_from_the_package() -> None:
    assert catalog.study_organisms is searches.study_organisms
    assert "study_organisms" in catalog.__all__


@pytest.mark.skipif(
    needs_qa_recording(TEST_ROOT / "unit/catalog/fixtures/plasmodb_all_datasets.json"),
    reason=NEEDS_QA_RECORDING,
)
async def test_a_host_reads_it_from_the_catalog_of_the_site(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    plasmodb = await recorded_catalog(monkeypatch, tmp_path, "plasmodb")

    async def _catalog(site_id: str) -> SearchCatalog:
        assert site_id == "plasmodb"
        return plasmodb

    service = MagicMock()
    service.get_catalog = _catalog
    monkeypatch.setattr(searches, "get_discovery_service", lambda: service)

    assert await catalog.study_organisms("plasmodb", "DS_eeca6a5476") == [
        "Plasmodium falciparum 3D7"
    ]

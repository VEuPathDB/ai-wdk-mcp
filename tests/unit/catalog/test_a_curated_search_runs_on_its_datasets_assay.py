"""A search runs on the assay every dataset that names it records, and a study
on the assay of its dataset record."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from tests._support.recorded_catalog import recorded_catalog

from veupathdb_mcp import catalog
from veupathdb_mcp.catalog import searches
from veupathdb_mcp.catalog.discovery import SearchCatalog

_HOMINIS_OOCYSTS = "GenesByRNASeqchomTU502_Widmer_oocysts_ebi_rnaSeq_RSRCPercentile"
_UV_MICROARRAY = (
    "GenesByMicroarrayDirectcparIowaII_microarrayExpression_Zhu_GSE34307_RSRC"
)


class TestTheCatalogMarksTheAssayASearchRunsOn:
    async def test_a_search_one_dataset_names_has_its_category(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        cryptodb = await recorded_catalog(monkeypatch, tmp_path, "cryptodb")

        assert [
            cryptodb.dataset_assay(name)
            for name in (_HOMINIS_OOCYSTS, _UV_MICROARRAY, "GenesByRtPcrFoldChange")
        ] == ["RNASeq", "DNA Microarray Assay", "RT PCR"]

    async def test_a_search_its_datasets_agree_on_has_their_category(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        cryptodb = await recorded_catalog(monkeypatch, tmp_path, "cryptodb")

        assert [
            cryptodb.dataset_assay(name)
            for name in (
                "GenesBySingleCell",
                "GenesByIntronJunctions",
                "GenesByMassSpec",
            )
        ] == ["scRNA-Seq", "RNASeq", "Protein expression"]

    @pytest.mark.parametrize("search_name", ["GeneByLocusTag", "GenesByEcNumber"])
    async def test_a_search_its_datasets_differ_on_has_none(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, search_name: str
    ) -> None:
        plasmodb = await recorded_catalog(monkeypatch, tmp_path, "plasmodb")

        assert plasmodb.dataset_assay(search_name) is None

    async def test_a_search_no_dataset_names_has_none(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        cryptodb = await recorded_catalog(monkeypatch, tmp_path, "cryptodb")

        assert cryptodb.dataset_assay("GenesByText") is None


class TestTheCatalogMarksTheAssayOfAStudy:
    async def test_a_study_has_the_category_of_its_dataset_record(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        plasmodb = await recorded_catalog(monkeypatch, tmp_path, "plasmodb")

        assert [
            plasmodb.study_assay(dataset_id)
            for dataset_id in ("DS_eeca6a5476", "DS_10068cde24", "DS_0fdca599cd")
        ] == ["RNASeq", "Phenotype", "Immunology"]

    async def test_a_record_with_no_category_has_its_type(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        cryptodb = await recorded_catalog(monkeypatch, tmp_path, "cryptodb")

        assert cryptodb.study_assay("DS_0d9651c265") == "isolates"

    @pytest.mark.parametrize("dataset_id", ["DS_6889a51dab", "EDAUD_lhZ5ptRgo014J"])
    async def test_a_study_the_site_publishes_no_assay_for_has_none(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, dataset_id: str
    ) -> None:
        cryptodb = await recorded_catalog(monkeypatch, tmp_path, "cryptodb")

        assert cryptodb.study_assay(dataset_id) is None


class TestAHostReadsTheAssay:
    def test_from_the_package(self) -> None:
        assert (catalog.dataset_assay, catalog.study_assay) == (
            searches.dataset_assay,
            searches.study_assay,
        )
        assert {"dataset_assay", "study_assay"} <= set(catalog.__all__)

    async def test_from_the_catalog_of_the_site(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        cryptodb = await recorded_catalog(monkeypatch, tmp_path, "cryptodb")
        asked: list[str] = []

        async def _catalog(site_id: str) -> SearchCatalog:
            asked.append(site_id)
            return cryptodb

        service = MagicMock()
        service.get_catalog = _catalog
        monkeypatch.setattr(searches, "get_discovery_service", lambda: service)

        read = (
            await catalog.dataset_assay("cryptodb", _HOMINIS_OOCYSTS),
            await catalog.study_assay("cryptodb", "DS_f7a8040723"),
        )

        assert read == ("RNASeq", "DNA Microarray Assay")
        assert asked == ["cryptodb", "cryptodb"]

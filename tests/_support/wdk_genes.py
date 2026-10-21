from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from veupathdb import JSONObject
from veupathdb.wdk import WDKAnswer, WDKDatasetConfigIdList, WDKSearchConfig

from veupathdb_mcp.audit import genes
from veupathdb_mcp.audit.genes import GeneRow

PIGA = "PF3D7_1032400"
PF3D7 = "Plasmodium falciparum 3D7"
FIXTURES = Path(__file__).resolve().parents[1] / "unit/audit/fixtures"


def gene_attributes(length: str, pseudo: str | None, gene_type: str) -> JSONObject:
    return {
        "organism_full": PF3D7,
        "gene_orthomcl_name": "OG8_0000001",
        "protein_length": length,
        "gene_name": "PIGA",
        "gene_product": (
            "phosphatidylinositol N-acetylglucosaminyltransferase subunit A"
        ),
        "sequence_id": "Pf3D7_10_v3",
        "gene_start_min": "1302298",
        "gene_end_max": "1305315",
        "strand_plus_minus": "-",
        "is_pseudo": pseudo,
        "gene_type": gene_type,
    }


def record(gene: str, transcript: str, attributes: JSONObject) -> JSONObject:
    return {
        "id": [
            {"name": "gene_source_id", "value": gene},
            {"name": "source_id", "value": transcript},
        ],
        "attributes": attributes,
    }


def coding(transcript: str = f"{PIGA}.1", length: str = "461") -> JSONObject:
    return record(
        PIGA, transcript, gene_attributes(length, "No", "protein coding gene")
    )


def protein(gene: str, transcript: str, sequence: str) -> JSONObject:
    return {
        "id": [
            {"name": "gene_source_id", "value": gene},
            {"name": "source_id", "value": transcript},
        ],
        "attributes": {"protein_sequence": sequence},
    }


def answer_of(records: list[JSONObject], total: int | None = -1) -> WDKAnswer:
    count = len(records) if total == -1 else total
    return WDKAnswer.model_validate(
        {
            "meta": {"totalCount": count, "responseCount": len(records)},
            "records": records,
        }
    )


class ReportSite:
    def __init__(self, answers: list[WDKAnswer]) -> None:
        self._answers = answers
        self.searches: list[tuple[str, str, WDKSearchConfig, JSONObject | None]] = []
        self.datasets: list[WDKDatasetConfigIdList] = []

    async def run_search_report(
        self,
        record_type: str,
        search_name: str,
        search_config: WDKSearchConfig,
        report_config: JSONObject | None = None,
    ) -> WDKAnswer:
        self.searches.append((record_type, search_name, search_config, report_config))
        return self._answers[len(self.searches) - 1]


class Datasets:
    def __init__(self, site: ReportSite) -> None:
        self._site = site

    async def create_dataset(self, config: WDKDatasetConfigIdList) -> int:
        self._site.datasets.append(config)
        return 9000 + len(self._site.datasets)


def serve(monkeypatch: pytest.MonkeyPatch, answers: list[WDKAnswer]) -> ReportSite:
    site = ReportSite(answers)
    monkeypatch.setattr(genes, "get_wdk_client", lambda site_id: site)
    monkeypatch.setattr(genes, "StrategyAPI", Datasets)
    return site


def serve_private(
    monkeypatch: pytest.MonkeyPatch, answers: list[WDKAnswer]
) -> tuple[ReportSite, ReportSite]:
    shared = serve(monkeypatch, [])
    private = ReportSite(answers)

    @asynccontextmanager
    async def opened(site_id: str) -> AsyncIterator[ReportSite]:
        yield private

    monkeypatch.setattr(genes, "dataset_client", opened)
    return shared, private


def piga(*, pseudo: bool | None) -> GeneRow:
    return GeneRow(
        gene=PIGA,
        organism=PF3D7,
        ortholog_group="OG8_0000001",
        protein_length=461,
        name="PIGA",
        product="phosphatidylinositol N-acetylglucosaminyltransferase subunit A",
        sequence_id="Pf3D7_10_v3",
        start=1302298,
        end=1305315,
        strand="-",
        pseudo=pseudo,
        gene_type="protein coding gene",
    )

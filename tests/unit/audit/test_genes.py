from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from pydantic import ValidationError
from veupathdb import JSONObject
from veupathdb.auth_context import veupathdb_auth_token_ctx
from veupathdb.errors import WDKError, WDKLoginRequiredError
from veupathdb.wdk import (
    WDKAnswer,
    WDKDatasetConfigIdList,
    WDKRecordInstance,
    WDKSearchConfig,
)

from veupathdb_mcp.audit import genes
from veupathdb_mcp.audit.genes import (
    GENE_ATTRIBUTES,
    GeneRow,
    gene_rows,
    genes_of_genome,
    proteins_of,
    rows_of,
)

PIGA = "PF3D7_1032400"


def record(
    gene: str, transcript: str, length: str, pseudo: str, gene_type: str
) -> dict[str, object]:
    return {
        "id": [
            {"name": "gene_source_id", "value": gene},
            {"name": "source_id", "value": transcript},
        ],
        "attributes": {
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
        },
    }


def coding(transcript: str = f"{PIGA}.1", length: str = "461") -> dict[str, object]:
    return record(PIGA, transcript, length, "No", "protein coding gene")


def protein(gene: str, transcript: str, sequence: str) -> dict[str, object]:
    return {
        "id": [
            {"name": "gene_source_id", "value": gene},
            {"name": "source_id", "value": transcript},
        ],
        "attributes": {"protein_sequence": sequence},
    }


def answer_of(records: list[dict[str, object]], total: int | None = -1) -> WDKAnswer:
    count = len(records) if total == -1 else total
    return WDKAnswer.model_validate(
        {
            "meta": {"totalCount": count, "responseCount": len(records)},
            "records": records,
        }
    )


class _Site:
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


class _Datasets:
    def __init__(self, site: _Site) -> None:
        self._site = site

    async def create_dataset(self, config: WDKDatasetConfigIdList) -> int:
        self._site.datasets.append(config)
        return 9000 + len(self._site.datasets)


def _serve(monkeypatch: pytest.MonkeyPatch, answers: list[WDKAnswer]) -> _Site:
    site = _Site(answers)
    monkeypatch.setattr(genes, "get_wdk_client", lambda site_id: site)
    monkeypatch.setattr(genes, "StrategyAPI", _Datasets)
    return site


def _serve_private(
    monkeypatch: pytest.MonkeyPatch, answers: list[WDKAnswer]
) -> tuple[_Site, _Site]:
    shared = _serve(monkeypatch, [])
    private = _Site(answers)

    @asynccontextmanager
    async def opened(site_id: str) -> AsyncIterator[_Site]:
        yield private

    monkeypatch.setattr(genes, "dataset_client", opened)
    return shared, private


def test_rows_keep_the_longest_protein_per_gene_and_read_pseudogenes() -> None:
    answer = answer_of(
        [
            coding(),
            coding(f"{PIGA}.2", "400"),
            record(
                "PfNF54_100037200:pseudogene",
                "PfNF54_100037200.1",
                "",
                "Yes",
                "pseudogene",
            ),
        ]
    )
    rows = {row.gene: row for row in rows_of(answer)}
    assert len(rows) == 2
    assert rows[PIGA].protein_length == 461
    assert rows[PIGA].strand == "-"
    assert rows[PIGA].pseudo is False
    assert rows["PfNF54_100037200:pseudogene"].protein_length is None
    assert rows["PfNF54_100037200:pseudogene"].pseudo is True


def piga(*, pseudo: bool) -> GeneRow:
    return GeneRow(
        gene=PIGA,
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


def test_a_row_is_read_from_one_transcript_record() -> None:
    row = GeneRow.from_record(WDKRecordInstance.model_validate(coding()))

    assert row == piga(pseudo=False)


@pytest.mark.parametrize("pseudo", [True, False])
def test_a_row_round_trips_through_its_dump(pseudo: bool) -> None:
    row = piga(pseudo=pseudo)

    assert GeneRow.model_validate(row.model_dump()) == row
    assert GeneRow.model_validate_json(row.model_dump_json()) == row


@pytest.mark.parametrize("pseudo", ["", "yes", "true", "1", "Unknown", 1, 0])
def test_a_pseudogene_flag_other_than_yes_no_or_a_bool_is_refused(
    pseudo: str | int,
) -> None:
    dumped = piga(pseudo=False).model_dump()

    with pytest.raises(ValidationError):
        GeneRow.model_validate({**dumped, "pseudo": pseudo})


def test_a_record_pseudogene_flag_other_than_yes_or_no_is_refused() -> None:
    with pytest.raises(ValidationError):
        rows_of(answer_of([record(PIGA, f"{PIGA}.1", "461", "yes", "pseudogene")]))


async def test_a_genome_is_read_from_one_taxon_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = _serve(monkeypatch, [answer_of([coding()])])

    rows = await genes_of_genome("plasmodb", "Plasmodium falciparum 3D7")

    assert [row.gene for row in rows] == [PIGA]
    assert len(site.searches) == 1
    record_type, search_name, config, report = site.searches[0]
    assert (record_type, search_name) == ("transcript", "GenesByTaxon")
    assert json.loads(config.parameters["organism"]) == ["Plasmodium falciparum 3D7"]
    assert report is not None
    assert report["attributes"] == list(GENE_ATTRIBUTES)
    assert report["tables"] == []


@pytest.mark.parametrize("total", [2, None])
async def test_a_genome_report_short_of_its_total_is_refused(
    monkeypatch: pytest.MonkeyPatch, total: int | None
) -> None:
    _serve(monkeypatch, [answer_of([coding()], total=total)])

    with pytest.raises(WDKError):
        await genes_of_genome("plasmodb", "Plasmodium falciparum 3D7")


async def test_proteins_are_read_150_ids_per_dataset_longest_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ids = [f"PF3D7_{n:07d}" for n in range(301)]
    shared, site = _serve_private(
        monkeypatch,
        [
            answer_of(
                [
                    protein(ids[0], f"{ids[0]}.1", "MKV*"),
                    protein(ids[0], f"{ids[0]}.2", "MKVLL*"),
                    protein(ids[0], f"{ids[0]}.3", "MK*"),
                ]
            ),
            answer_of([protein(ids[150], f"{ids[150]}.1", "MSS")]),
            answer_of([protein(ids[300], f"{ids[300]}.1", "MAA*")]),
        ],
    )

    found = await proteins_of("plasmodb", ids)

    assert found == {ids[0]: "MKVLL", ids[150]: "MSS", ids[300]: "MAA"}
    assert [dataset.source_content.ids for dataset in site.datasets] == [
        ids[0:150],
        ids[150:300],
        ids[300:301],
    ]
    assert [search[1] for search in site.searches] == ["GeneByLocusTag"] * 3
    assert [search[2].parameters["ds_gene_ids"] for search in site.searches] == [
        "9001",
        "9002",
        "9003",
    ]
    assert site.searches[0][3] == {
        "attributes": ["protein_sequence"],
        "tables": [],
        "pagination": {"offset": 0, "numRecords": 1200},
    }
    assert shared.searches == []
    assert shared.datasets == []


async def test_a_protein_report_short_of_its_total_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _serve_private(
        monkeypatch, [answer_of([protein(PIGA, f"{PIGA}.1", "MKV*")], total=9)]
    )

    with pytest.raises(WDKError):
        await proteins_of("plasmodb", [PIGA])


async def test_no_genes_read_no_proteins_and_need_no_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = _serve(monkeypatch, [])
    reset = veupathdb_auth_token_ctx.set(None)
    try:
        found = await proteins_of("plasmodb", [])
    finally:
        veupathdb_auth_token_ctx.reset(reset)

    assert found == {}
    assert site.datasets == []
    assert site.searches == []


async def test_proteins_with_no_researcher_token_are_refused_before_a_dataset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = _serve(monkeypatch, [])
    reset = veupathdb_auth_token_ctx.set(None)
    try:
        with pytest.raises(WDKLoginRequiredError):
            await proteins_of("plasmodb", [PIGA])
    finally:
        veupathdb_auth_token_ctx.reset(reset)

    assert site.datasets == []
    assert site.searches == []


async def test_gene_rows_are_read_from_one_locus_tag_report_on_a_private_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shared, site = _serve_private(monkeypatch, [answer_of([coding()])])

    rows = await gene_rows("plasmodb", [PIGA, "PfNF54_100037200"])

    assert rows == [piga(pseudo=False)]
    assert [dataset.source_content.ids for dataset in site.datasets] == [
        [PIGA, "PfNF54_100037200"]
    ]
    assert [(search[0], search[1]) for search in site.searches] == [
        ("transcript", "GeneByLocusTag")
    ]
    assert site.searches[0][2].parameters["ds_gene_ids"] == "9001"
    assert site.searches[0][3] == {
        "attributes": list(GENE_ATTRIBUTES),
        "tables": [],
        "pagination": {"offset": 0, "numRecords": 16},
    }
    assert shared.searches == []
    assert shared.datasets == []


async def test_a_gene_row_report_short_of_its_total_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _serve_private(monkeypatch, [answer_of([coding()], total=3)])

    with pytest.raises(WDKError):
        await gene_rows("plasmodb", [PIGA])


async def test_no_genes_read_no_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    shared, site = _serve_private(monkeypatch, [])

    assert await gene_rows("plasmodb", []) == []
    assert site.datasets == []
    assert shared.datasets == []

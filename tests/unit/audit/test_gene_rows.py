from __future__ import annotations

import json
import re

import pytest
from pydantic import ValidationError
from tests._support.wdk_genes import (
    PF3D7,
    PIGA,
    answer_of,
    coding,
    gene_attributes,
    piga,
    protein,
    record,
    serve,
    serve_private,
)
from veupathdb import JSONObject
from veupathdb.auth_context import veupathdb_auth_token_ctx
from veupathdb.errors import (
    DataParsingError,
    WDKError,
    WDKLoginRequiredError,
)
from veupathdb.wdk import (
    WDKRecordInstance,
)

from veupathdb_mcp.audit.genes import (
    GENE_ATTRIBUTES,
    GeneRow,
    gene_rows,
    genes_of_genome,
    proteins_of,
    rows_of,
)


def test_rows_keep_the_longest_protein_per_gene_and_read_pseudogenes() -> None:
    answer = answer_of(
        [
            coding(),
            coding(f"{PIGA}.2", "400"),
            record(
                "PfNF54_100037200:pseudogene",
                "PfNF54_100037200.1",
                gene_attributes("", "Yes", "pseudogene"),
            ),
        ]
    )
    rows = {row.gene: row for row in rows_of(answer, "GeneByLocusTag")}
    assert len(rows) == 2
    assert rows[PIGA].protein_length == 461
    assert rows[PIGA].strand == "-"
    assert rows[PIGA].pseudo is False
    assert rows["PfNF54_100037200:pseudogene"].protein_length is None
    assert rows["PfNF54_100037200:pseudogene"].pseudo is True


def test_a_row_is_read_from_one_transcript_record() -> None:
    row = GeneRow.from_record(WDKRecordInstance.model_validate(coding()))

    assert row == piga(pseudo=False)


@pytest.mark.parametrize("pseudo", [True, False, None])
def test_a_row_round_trips_through_its_dump(pseudo: bool | None) -> None:
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


def test_a_record_that_serves_no_pseudogene_flag_reads_an_unknown_flag() -> None:
    served = record(
        PIGA, f"{PIGA}.1", gene_attributes("461", None, "protein coding gene")
    )

    [row] = rows_of(answer_of([served]), "GeneByLocusTag")

    assert row.pseudo is None
    assert row == piga(pseudo=None)


def test_a_record_that_is_not_a_gene_row_is_refused_naming_the_search() -> None:
    served = record(PIGA, f"{PIGA}.1", gene_attributes("461", "yes", "pseudogene"))

    with pytest.raises(
        DataParsingError,
        match=re.escape(
            "the WDK GeneByLocusTag report served a record "
            f"(gene_source_id={PIGA}, source_id={PIGA}.1) "
            "that is not a gene row: unreadable pseudo"
        ),
    ):
        rows_of(answer_of([served]), "GeneByLocusTag")


async def test_a_genome_is_read_from_one_taxon_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = serve(monkeypatch, [answer_of([coding()])])

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
    serve(monkeypatch, [answer_of([coding()], total=total)])

    with pytest.raises(WDKError):
        await genes_of_genome("plasmodb", "Plasmodium falciparum 3D7")


async def test_proteins_are_read_150_ids_per_dataset_longest_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ids = [f"PF3D7_{n:07d}" for n in range(301)]
    shared, site = serve_private(
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
    serve_private(
        monkeypatch, [answer_of([protein(PIGA, f"{PIGA}.1", "MKV*")], total=9)]
    )

    with pytest.raises(WDKError):
        await proteins_of("plasmodb", [PIGA])


async def test_no_genes_read_no_proteins_and_need_no_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = serve(monkeypatch, [])
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
    site = serve(monkeypatch, [])
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
    shared, site = serve_private(monkeypatch, [answer_of([coding()])])

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
    serve_private(monkeypatch, [answer_of([coding()], total=3)])

    with pytest.raises(WDKError):
        await gene_rows("plasmodb", [PIGA])


async def test_no_genes_read_no_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    shared, site = serve_private(monkeypatch, [])

    assert await gene_rows("plasmodb", []) == []
    assert site.datasets == []
    assert shared.datasets == []


def test_a_row_reads_its_organism() -> None:
    row = GeneRow.from_record(WDKRecordInstance.model_validate(coding()))

    assert row.organism == PF3D7
    assert "organism_full" in GENE_ATTRIBUTES


def test_a_record_without_an_organism_is_refused() -> None:
    attributes: JSONObject = {
        **gene_attributes("461", "No", "protein coding gene"),
        "organism_full": "",
    }
    raw = record(PIGA, f"{PIGA}.1", attributes)

    with pytest.raises(ValidationError):
        GeneRow.from_record(WDKRecordInstance.model_validate(raw))

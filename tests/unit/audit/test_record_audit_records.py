from pathlib import Path

import pytest
from scripts.record_audit_records import (
    CASES,
    MISSING_PROTEINS,
    PIGA_FILE,
    RecordExchange,
    RecordWire,
    StoreExchange,
    read_wire,
    write,
)
from tests._support.audit_wire import ServedRecords
from tests._support.intron_wire import load_introns
from tests._support.record_site import (
    FIXTURES,
    install_recorded_records,
    install_store,
    load_records,
    record_key,
)
from tests._support.row_reads import recorded_answers
from veupathdb.wdk import WDKRecordInstance

from veupathdb_mcp.audit import gene_models
from veupathdb_mcp.audit.genes import LOCUS_TAG, orthologs_of, proteins_in, rows_of
from veupathdb_mcp.audit.introns_inputs import ORTHOLOG_PROTEINS_READ, ortholog_choice
from veupathdb_mcp.audit.record_reads import record_rows
from veupathdb_mcp.tools.audit_intron_tools import audit_intron_support

QA_HOSTS = (
    "https://qa.fungidb.org/",
    "https://qa.vectorbase.org/",
    "https://qa.toxodb.org/",
)


def test_the_cases_are_the_four_recorded_introns() -> None:
    assert [(c.site, c.gene, c.file, c.orthologs) for c in CASES] == [
        ("fungidb", "Afu8g00850", "introns_afumAf293_afu8g00850.json.xz", True),
        ("vectorbase", "AGAP007279", "introns_agamPEST_agap007279.json.xz", False),
        ("toxodb", "TGME49_224540", "introns_tgonME49_tgme49_224540.json.xz", False),
        ("vectorbase", "AGAP003685", "introns_agamPEST_agap003685.json.xz", True),
    ]


@pytest.mark.parametrize("case", [c for c in CASES if c.orthologs])
async def test_a_case_records_the_proteins_the_check_chooses(
    monkeypatch: pytest.MonkeyPatch, case
) -> None:
    wire = load_records(case.file)
    install_recorded_records(monkeypatch, wire)
    [row] = await record_rows(case.site, [case.gene])
    chosen = ortholog_choice(await orthologs_of(case.site, case.gene), row)
    read = [
        r.primary_key["gene_source_id"]
        for r in wire.records
        if r.record_type == "transcript"
    ]

    assert len(chosen) == ORTHOLOG_PROTEINS_READ
    assert read == [case.gene, *chosen]


@pytest.mark.parametrize("case", CASES)
def test_every_store_read_is_a_qa_read_the_site_answered(case) -> None:
    wire = load_records(case.file)

    assert wire.site == case.site
    assert all(e.url.startswith(QA_HOSTS) for e in wire.store)
    assert {e.status for e in wire.store} <= {200, 206}
    assert {r.status for r in wire.records} == {200}


@pytest.mark.parametrize(
    ("proteins", "introns", "gene"),
    [
        ("introns_pcynM_pkac_proteins.json", "introns_pcynM_pkac.json", "PcyM_0736700"),
        (
            "introns_afumAf293_dmaw_proteins.json",
            "introns_afumAf293_dmaw.json",
            "Afu2g18040",
        ),
    ],
)
async def test_the_older_cases_record_only_the_proteins_their_reports_lack(
    monkeypatch: pytest.MonkeyPatch, proteins: str, introns: str, gene: str
) -> None:
    old = load_introns(introns)
    table = ServedRecords([WDKRecordInstance.model_validate(old.ortholog_record)])
    monkeypatch.setattr(gene_models, "get_strategy_api", lambda site_id: table)
    [row] = rows_of(recorded_answers(old.gene_answers)[0], LOCUS_TAG)
    chosen = ortholog_choice(await orthologs_of(old.site, gene), row)
    held = proteins_in(recorded_answers(old.ortholog_protein_answers))

    assert MISSING_PROTEINS[proteins] == (
        old.site,
        [named for named in chosen if named not in held],
    )
    assert {r.primary_key["source_id"] for r in load_records(proteins).records} >= set(
        MISSING_PROTEINS[proteins][1]
    )


def test_a_written_recording_reads_back_unchanged(tmp_path: Path) -> None:
    wire = RecordWire(
        site="plasmodb",
        transcript_key=["gene_source_id", "source_id", "project_id"],
        records=[
            RecordExchange(
                record_type="gene",
                primary_key={"source_id": "EXA_0001", "project_id": "PlasmoDB"},
                attributes=[],
                tables=["GeneTranscripts"],
                status=200,
                body={"id": [], "attributes": {}, "tables": {}},
            )
        ],
        store=[
            StoreExchange(
                url="https://qa.plasmodb.org/plasmo.qa/service/jbrowse/store?data=x",
                byte_range="bytes=0-3",
                status=206,
                body=b"QUFBQQ==",
            )
        ],
    )

    write(tmp_path, "records_example.json", wire)

    read = RecordWire.model_validate_json(
        (tmp_path / "records_example.json").read_text()
    )
    assert read == wire
    assert read.store[0].body == b"AAAA"
    assert not (FIXTURES / "records_example.json").exists()
    assert (FIXTURES / PIGA_FILE).exists()


def test_a_compressed_recording_reads_back_unchanged(tmp_path: Path) -> None:
    wire = RecordWire(site="plasmodb", transcript_key=[], records=[])

    write(tmp_path, "records_example.json.xz", wire)

    assert read_wire(tmp_path / "records_example.json.xz") == wire
    assert (tmp_path / "records_example.json.xz").read_bytes()[:6] == b"\xfd7zXZ\x00"


@pytest.mark.parametrize("case", CASES)
async def test_a_case_holds_only_what_the_check_reads(
    monkeypatch: pytest.MonkeyPatch, case
) -> None:
    wire = load_records(case.file)
    records = install_recorded_records(monkeypatch, wire)
    store = install_store(monkeypatch, wire)

    await audit_intron_support(wire.site, case.gene)

    assert sorted(set(store.served)) == sorted(
        (e.url, e.byte_range) for e in wire.store
    )
    assert sorted(records.served) == sorted(
        record_key(r.record_type, r.primary_key, r.attributes, r.tables)
        for r in wire.records
    )

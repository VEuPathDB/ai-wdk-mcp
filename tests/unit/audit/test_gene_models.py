import pytest
from pydantic import ValidationError
from veupathdb.errors import DataParsingError
from veupathdb.wdk import WDKRecordInstance

from veupathdb_mcp.audit import gene_models
from veupathdb_mcp.audit.gene_models import (
    MODEL_TABLE,
    GeneModel,
    ModelRow,
    coding_parts,
    gene_model,
    gene_record,
)
from veupathdb_mcp.audit.pseudogene import CdsPart

PIGA = "PF3D7_1032400"


def row(kind: str, start: int, end: int, transcript: str = f"{PIGA}.1"):
    return {
        "strand": "-",
        "sequence_id": "Pf3D7_10_v3",
        "source_id": PIGA,
        "type": kind,
        "transcript_ids": transcript,
        "gm_end": str(end),
        "gm_start": str(start),
    }


MODEL = [
    row("five_prime_UTR", 1304882, 1305315),
    row("Exon", 1304710, 1305315),
    row("CDS", 1304710, 1304881),
    row("Intron", 1304501, 1304709),
    row("CDS", 1302594, 1302660),
    row("CDS", 1302500, 1302660, transcript=f"{PIGA}.2"),
    row("three_prime_UTR", 1302298, 1302593),
]


def record(organism: str, model: list[dict[str, str]]) -> WDKRecordInstance:
    return WDKRecordInstance.model_validate(
        {
            "id": [
                {"name": "source_id", "value": PIGA},
                {"name": "project_id", "value": "PlasmoDB"},
            ],
            "attributes": {"organismAbbrev": organism},
            "tables": {MODEL_TABLE: model},
        }
    )


def test_the_coding_parts_are_the_cds_rows_of_the_longest_transcript() -> None:
    rows = [ModelRow.model_validate(raw) for raw in MODEL]

    assert coding_parts(rows) == [
        CdsPart(start=1302594, end=1302660),
        CdsPart(start=1304710, end=1304881),
    ]


def test_a_row_shared_by_several_transcripts_belongs_to_each() -> None:
    rows = [
        ModelRow.model_validate(row("CDS", 100, 200, transcript="G.1,G.2")),
        ModelRow.model_validate(row("CDS", 300, 400, transcript="G.1")),
        ModelRow.model_validate(row("CDS", 300, 450, transcript="G.2")),
        ModelRow.model_validate(row("CDS", 500, 600, transcript="G.1, G.2")),
    ]

    assert rows[0].transcript_ids == frozenset({"G.1", "G.2"})
    assert coding_parts(rows) == [
        CdsPart(start=100, end=200),
        CdsPart(start=300, end=450),
        CdsPart(start=500, end=600),
    ]


def test_the_longest_transcript_wins_over_a_lexically_first_one() -> None:
    rows = [
        ModelRow.model_validate(row("CDS", 100, 200, transcript="G.10")),
        ModelRow.model_validate(row("CDS", 100, 200, transcript="G.2")),
        ModelRow.model_validate(row("CDS", 300, 400, transcript="G.2")),
    ]

    assert coding_parts(rows) == [
        CdsPart(start=100, end=200),
        CdsPart(start=300, end=400),
    ]


def test_transcripts_of_equal_length_are_taken_by_id() -> None:
    rows = [
        ModelRow.model_validate(row("CDS", 300, 400, transcript="G.2")),
        ModelRow.model_validate(row("CDS", 100, 200, transcript="G.1")),
    ]

    assert coding_parts(rows) == [CdsPart(start=100, end=200)]


def test_a_model_row_round_trips_through_its_dump() -> None:
    parsed = ModelRow.model_validate(row("CDS", 100, 200, transcript="G.1,G.2"))

    assert ModelRow.model_validate(parsed.model_dump()) == parsed


def test_a_model_without_cds_rows_has_no_coding_parts() -> None:
    rows = [ModelRow.model_validate(raw) for raw in MODEL if raw["type"] != "CDS"]

    assert coding_parts(rows) == []


def test_a_gene_model_reads_its_organism_and_its_coding_parts() -> None:
    model = GeneModel.from_record(record("pfal3D7", MODEL))

    assert model.organism_abbrev == "pfal3D7"
    assert model.cds == [
        CdsPart(start=1302594, end=1302660),
        CdsPart(start=1304710, end=1304881),
    ]


def test_a_record_without_an_organism_is_refused() -> None:
    with pytest.raises(ValidationError):
        GeneModel.from_record(record("", MODEL))


class _Records:
    def __init__(self, answer: WDKRecordInstance) -> None:
        self.answer = answer
        self.reads: list[tuple[str, list[dict[str, str]], list[str], list[str]]] = []

    async def get_single_record(
        self,
        record_type: str,
        primary_key: list[dict[str, str]],
        *,
        attributes: list[str],
        tables: list[str],
    ) -> WDKRecordInstance:
        self.reads.append((record_type, primary_key, attributes, tables))
        return self.answer


async def test_a_gene_model_is_one_gene_record_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = _Records(record("pfal3D7", MODEL))
    monkeypatch.setattr(gene_models, "get_strategy_api", lambda site_id: records)

    model = await gene_model("plasmodb", PIGA)

    assert model.organism_abbrev == "pfal3D7"
    assert len(model.cds) == 2
    assert records.reads == [
        (
            "gene",
            [
                {"name": "source_id", "value": PIGA},
                {"name": "project_id", "value": "PlasmoDB"},
            ],
            ["organismAbbrev"],
            ["GeneModelDump"],
        )
    ]


async def test_a_gene_record_is_read_by_source_id_and_project(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = _Records(record("pfal3D7", MODEL))
    monkeypatch.setattr(gene_models, "get_strategy_api", lambda site_id: records)

    read = await gene_record("toxodb", "TGME49_316600", ["a"], ["T"])

    assert read == records.answer
    assert records.reads == [
        (
            "gene",
            [
                {"name": "source_id", "value": "TGME49_316600"},
                {"name": "project_id", "value": "ToxoDB"},
            ],
            ["a"],
            ["T"],
        )
    ]


@pytest.mark.parametrize("organism", ["", None])
async def test_a_gene_record_without_an_organism_is_a_refusal_naming_the_gene(
    monkeypatch: pytest.MonkeyPatch, organism: str | None
) -> None:
    answer = record("pfal3D7", MODEL)
    attributes = {} if organism is None else {"organismAbbrev": organism}
    records = _Records(answer.model_copy(update={"attributes": attributes}))
    monkeypatch.setattr(gene_models, "get_strategy_api", lambda site_id: records)

    with pytest.raises(DataParsingError, match="gene record of PF3D7_1032400 on"):
        await gene_model("plasmodb", PIGA)

import pytest
from pydantic import ValidationError
from veupathdb.errors import DataParsingError
from veupathdb.wdk import WDKRecordInstance

from veupathdb_mcp.audit import gene_models
from veupathdb_mcp.audit.gene_models import (
    MODEL_TABLE,
    GeneModel,
    ModelRecord,
    ModelRow,
    ModelSpans,
    ReadModels,
    check_models,
    coding_parts,
    gene_model,
    gene_organism,
    gene_record,
    model_spans,
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


def test_the_spans_are_the_rows_of_the_transcript_the_coding_parts_take() -> None:
    rows = [ModelRow.model_validate(raw) for raw in MODEL]

    assert model_spans(PIGA, rows) == ModelSpans(
        gene=PIGA,
        transcript=f"{PIGA}.1",
        seqid="Pf3D7_10_v3",
        strand="-",
        exons=[(1304710, 1305315)],
        cds=[(1302594, 1302660), (1304710, 1304881)],
    )


def test_the_spans_of_equal_transcripts_are_those_of_the_first_by_id() -> None:
    rows = [
        ModelRow.model_validate(row(kind, 100, 200, transcript=transcript))
        for kind in ("CDS", "Exon")
        for transcript in ("G.2", "G.1")
    ]

    assert model_spans("G", rows).transcript == "G.1"


def test_rows_on_two_sequences_are_refused_naming_the_gene() -> None:
    rows = [ModelRow.model_validate(raw) for raw in MODEL]
    moved = rows[2].model_copy(update={"sequence_id": "Pf3D7_11_v3"})

    with pytest.raises(DataParsingError, match=f"{PIGA} lie on more than one"):
        model_spans(PIGA, [*rows[:2], moved, *rows[3:]])


def test_rows_on_two_strands_are_refused_naming_the_gene() -> None:
    rows = [ModelRow.model_validate(raw) for raw in MODEL]
    flipped = rows[1].model_copy(update={"strand": "+"})

    with pytest.raises(DataParsingError, match=f"{PIGA} lie on more than one"):
        model_spans(PIGA, [rows[0], flipped, *rows[2:]])


@pytest.mark.parametrize("dropped", ["CDS", "Exon"])
def test_a_model_without_cds_or_exon_rows_has_no_spans(dropped: str) -> None:
    rows = [ModelRow.model_validate(raw) for raw in MODEL if raw["type"] != dropped]

    with pytest.raises(DataParsingError, match=f"{PIGA} gives no {dropped}"):
        model_spans(PIGA, rows)


def test_a_model_row_names_its_sequence_and_strand() -> None:
    raw = row("CDS", 100, 200)
    del raw["strand"]

    with pytest.raises(ValidationError, match="strand"):
        ModelRow.model_validate(raw)


def test_a_model_record_serves_the_spans_of_its_gene() -> None:
    rows = [ModelRow.model_validate(raw) for raw in MODEL]
    model = GeneModel(organism_abbrev="pfal3D7", cds=coding_parts(rows))

    found = ModelRecord(gene=PIGA, model=model, rows=rows)

    assert found.spans == model_spans(PIGA, rows)


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


async def test_a_gene_organism_is_one_record_read_with_no_table(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = _Records(record("pfalNF54", []))
    monkeypatch.setattr(gene_models, "get_strategy_api", lambda site_id: records)

    assert await gene_organism("plasmodb", PIGA) == "pfalNF54"
    [(_, _, attributes, tables)] = records.reads
    assert (attributes, tables) == (["organismAbbrev"], [])


@pytest.mark.parametrize("organism", ["", None])
async def test_a_gene_organism_the_record_does_not_give_is_a_refusal(
    monkeypatch: pytest.MonkeyPatch, organism: str | None
) -> None:
    attributes = {} if organism is None else {"organismAbbrev": organism}
    answer = record("pfal3D7", []).model_copy(update={"attributes": attributes})
    monkeypatch.setattr(
        gene_models, "get_strategy_api", lambda site_id: _Records(answer)
    )

    with pytest.raises(
        DataParsingError,
        match="gene record of PF3D7_1032400 on plasmodb gives no organismAbbrev",
    ):
        await gene_organism("plasmodb", PIGA)


async def test_a_model_record_serves_the_model_and_its_rows_from_one_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reads: list[tuple[str, list[str], list[str]]] = []

    async def record(
        site_id: str, gene: str, attributes: list[str], tables: list[str]
    ) -> WDKRecordInstance:
        reads.append((gene, attributes, tables))
        return WDKRecordInstance.model_validate(
            {
                "attributes": {"organismAbbrev": "pfal3D7"},
                "tables": {
                    "GeneModelDump": [
                        {
                            "type": "CDS",
                            "transcript_ids": "t1",
                            "sequence_id": "c1",
                            "strand": "+",
                            "gm_start": 10,
                            "gm_end": 30,
                        },
                        {
                            "type": "Exon",
                            "transcript_ids": "t1",
                            "sequence_id": "c1",
                            "strand": "+",
                            "gm_start": 1,
                            "gm_end": 40,
                        },
                    ]
                },
            }
        )

    monkeypatch.setattr(gene_models, "gene_record", record)

    found = await gene_models.model_record("plasmodb", "G1")

    assert found.model == GeneModel(
        organism_abbrev="pfal3D7", cds=[CdsPart(start=10, end=30)]
    )
    assert [(row.type, row.gm_start) for row in found.rows] == [
        ("CDS", 10),
        ("Exon", 1),
    ]
    assert reads == [("G1", ["organismAbbrev"], ["GeneModelDump"])]
    assert found.spans == ModelSpans(
        gene="G1",
        transcript="t1",
        seqid="c1",
        strand="+",
        exons=[(1, 40)],
        cds=[(10, 30)],
    )


def test_the_models_not_read_are_none_beside_their_reasons() -> None:
    rows = [ModelRow.model_validate(raw) for raw in MODEL]
    uncoded = [found for found in rows if found.type != "CDS"]
    model = GeneModel(organism_abbrev="pfal3D7", cds=coding_parts(rows))
    empty = GeneModel(organism_abbrev="pfal3D7", cds=[])

    read = ReadModels.of(
        [
            ModelRecord(gene=PIGA, model=model, rows=rows),
            ModelRecord(gene="G2", model=empty, rows=uncoded),
        ]
    )

    assert read.models == [model_spans(PIGA, rows), None]
    assert read.evidence_unread == [f"the {MODEL_TABLE} of G2 gives no CDS row"]


def test_a_model_not_read_states_why() -> None:
    with pytest.raises(ValidationError, match="reason"):
        ReadModels(models=[None])


def test_a_model_not_read_holds_the_place_of_its_gene() -> None:
    rows = [ModelRow.model_validate(raw) for raw in MODEL]
    read = model_spans(PIGA, rows)

    check_models([None, read], ["G1", PIGA])
    with pytest.raises(ValueError, match="gene models name"):
        check_models([read, None], ["G1", PIGA])
    with pytest.raises(ValueError, match="gene models name"):
        check_models([None], ["G1", PIGA])

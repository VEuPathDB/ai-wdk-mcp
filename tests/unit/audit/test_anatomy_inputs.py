from pydantic import BaseModel, Field
from tests._support.anatomy_site import NF54_PIGA, PIGA, PIGA_FILE, recording
from veupathdb.wdk import WDKRecordInstance

from veupathdb_mcp.audit.anatomy_inputs import model_segments
from veupathdb_mcp.audit.gene_models import MODEL_TABLE, ModelRow


class ModelTable(BaseModel):
    rows: list[ModelRow] = Field(validation_alias=MODEL_TABLE)


def rows(*served: tuple[str, str, int, int]) -> list[ModelRow]:
    return [
        ModelRow.model_validate(
            {
                "type": kind,
                "transcript_ids": transcripts,
                "gm_start": str(start),
                "gm_end": str(end),
            }
        )
        for kind, transcripts, start, end in served
    ]


def recorded_rows(gene: str) -> list[ModelRow]:
    record = WDKRecordInstance.model_validate(recording(PIGA_FILE).records[gene])
    return ModelTable.model_validate(record.tables).rows


def test_the_segments_of_a_pseudogene_are_its_exon_rows_in_genome_order() -> None:
    assert model_segments(recorded_rows(NF54_PIGA)) == [
        (1063699, 1063980),
        (1064067, 1064156),
        (1064288, 1064329),
        (1064535, 1065602),
        (1065812, 1065985),
    ]


def test_the_segments_of_a_coding_gene_are_its_exons_not_its_cds_or_utr() -> None:
    segments = model_segments(recorded_rows(PIGA))

    assert len(segments) == 7
    assert segments[0] == (1302298, 1302660)
    assert segments[-1] == (1304710, 1305315)


def test_the_longest_transcript_gives_the_segments() -> None:
    served = rows(
        ("Exon", "t.1", 100, 200),
        ("Intron", "t.1", 201, 299),
        ("Exon", "t.1", 300, 400),
        ("Exon", "t.2", 100, 400),
        ("Exon", "t.2", 500, 501),
        ("CDS", "t.1, t.2", 100, 400),
    )

    assert model_segments(served) == [(100, 400), (500, 501)]


def test_a_tie_between_transcripts_takes_the_first_name() -> None:
    served = rows(("Exon", "t.2", 1, 10), ("Exon", "t.1", 21, 30))

    assert model_segments(served) == [(21, 30)]


def test_a_model_without_exon_rows_has_no_segments() -> None:
    assert model_segments(rows(("CDS", "t.1", 1, 30))) == []

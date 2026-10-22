import pytest
from veupathdb.wdk import WDKRecordInstance

from veupathdb_mcp.audit import MODEL_READS_PER_FINDING, gene_models
from veupathdb_mcp.audit.gene_models import ModelReads


def served(gene: str) -> WDKRecordInstance:
    return WDKRecordInstance.model_validate(
        {
            "id": [{"name": "source_id", "value": gene}],
            "attributes": {"organismAbbrev": "pfal3D7"},
            "tables": {
                "GeneModelDump": [
                    {
                        "type": kind,
                        "transcript_ids": f"{gene}.1",
                        "sequence_id": "c1",
                        "strand": "+",
                        "gm_start": 10,
                        "gm_end": 30,
                    }
                    for kind in ("CDS", "Exon")
                ]
            },
        }
    )


class Records:
    def __init__(self) -> None:
        self.reads: list[tuple[str, list[str], list[str]]] = []

    async def read(
        self, site_id: str, gene: str, attributes: list[str], tables: list[str]
    ) -> WDKRecordInstance:
        self.reads.append((gene, attributes, tables))
        return served(gene)


def test_a_finding_reads_at_most_two_models() -> None:
    assert MODEL_READS_PER_FINDING == 2


async def test_two_model_reads_in_one_call_are_two_gene_record_reads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = Records()
    monkeypatch.setattr(gene_models, "gene_record", records.read)
    reads = ModelReads("plasmodb")

    first = await reads.read("G1")
    second = await reads.read("G2")

    assert [first.spans.gene, second.spans.gene] == ["G1", "G2"]
    assert first.spans.cds == [(10, 30)]
    assert records.reads == [
        ("G1", ["organismAbbrev"], ["GeneModelDump"]),
        ("G2", ["organismAbbrev"], ["GeneModelDump"]),
    ]


async def test_a_third_model_read_in_one_call_is_refused_unsent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = Records()
    monkeypatch.setattr(gene_models, "gene_record", records.read)
    reads = ModelReads("plasmodb")
    await reads.read("G1")
    await reads.read("G2")

    with pytest.raises(ValueError, match="at most 2 gene models"):
        await reads.read("G3")

    assert [gene for gene, _, _ in records.reads] == ["G1", "G2"]

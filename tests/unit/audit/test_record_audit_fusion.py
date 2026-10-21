from pathlib import Path

import pytest
from scripts.record_audit_fusion import (
    CASES,
    FusionRecording,
    trim,
    write_recording,
)
from scripts.record_audit_missing import DatasetCall, SearchCall, WireCall
from tests._support.wdk_genes import gene_attributes, record
from veupathdb import JSONObject
from veupathdb.wdk import WDKRecordInstance

from veupathdb_mcp.audit.genes import GeneRow


def placed(gene: str, transcript: str, seqid: str, start: int) -> JSONObject:
    attributes = gene_attributes("300", "No", "protein coding gene")
    attributes |= {"sequence_id": seqid, "gene_start_min": str(start)}
    return record(gene, transcript, attributes)


def genome(records: list[JSONObject]) -> SearchCall:
    return SearchCall(
        record_type="transcript",
        search_name="GenesByTaxon",
        parameters={"organism": '["Plasmodium falciparum 3D7"]'},
        report=None,
        records=records,
        served_total=len(records),
    )


def kept(call: WireCall) -> list[str]:
    match call:
        case SearchCall(records=records):
            return [
                GeneRow.from_record(WDKRecordInstance.model_validate(raw)).gene
                for raw in records
            ]
        case _:
            return []


def contig() -> list[JSONObject]:
    return [
        *(placed(f"G{i}", f"G{i}.1", "chr1", 1000 * i + 1) for i in range(10)),
        placed("G5", "G5.2", "chr1", 5001),
        placed("H1", "H1.1", "chr2", 5001),
    ]


def test_the_cases_are_the_fragile_rpt6_merge_and_the_me49_pbgs_model() -> None:
    assert sorted((c.file, c.site, c.gene) for c in CASES.values()) == [
        ("fusion_pfraNilgiri_rpt6.json", "plasmodb", "AK88_02763"),
        ("fusion_tgonME49_pbgs.json", "toxodb", "TGME49_500302"),
    ]


def test_a_genome_report_keeps_one_gene_past_the_reach_and_one_other_sequence() -> None:
    [call] = trim([genome(contig())], {"G5", "MISSING"})

    assert kept(call) == [*(f"G{i}" for i in range(1, 10)), "G5", "H1"]
    match call:
        case SearchCall() as search:
            assert (search.kept, search.total) == (
                (
                    "G5, the 4 genes on each side of it on its sequence and the "
                    "gene of another sequence that starts nearest to it"
                ),
                11,
            )
        case _:
            pytest.fail("the trimmed call is not a search")


def test_a_genome_of_one_sequence_keeps_no_other_gene() -> None:
    one = contig()[:-1]

    [call] = trim([genome(one)], {"G0"})

    assert kept(call) == ["G0", "G1", "G2", "G3", "G4"]


def test_calls_that_are_not_genome_reports_are_kept_whole() -> None:
    dataset = DatasetCall(ids=["G1"], dataset=7)
    locus = genome(contig()).model_copy(update={"search_name": "GeneByLocusTag"})

    assert trim([dataset, locus], {"G5"}) == [dataset, locus]


def test_a_genome_report_without_a_centre_is_refused() -> None:
    with pytest.raises(ValueError, match="holds none of A, B"):
        trim([genome(contig())], {"B", "A"})


def test_a_recording_reads_back(tmp_path: Path) -> None:
    recorded = FusionRecording(
        case=CASES["tgonME49_pbgs"], calls=[DatasetCall(ids=["G1"], dataset=7)]
    )

    write_recording(tmp_path, recorded)

    written = (tmp_path / "fusion_tgonME49_pbgs.json").read_text()
    assert FusionRecording.model_validate_json(written) == recorded

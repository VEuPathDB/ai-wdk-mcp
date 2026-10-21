import json
from pathlib import Path

from scripts.record_audit_missing import (
    CASES,
    DatasetCall,
    MissingRecording,
    SearchCall,
    WindowCall,
    WireCall,
    trim,
    write_recording,
)
from tests._support.wdk_genes import gene_attributes, record
from veupathdb import JSONObject
from veupathdb.wdk import WDKRecordInstance

from veupathdb_mcp.audit.genes import GeneRow

ARI = "Toxoplasma gondii ARI"
GT1 = "Toxoplasma gondii GT1"
CASE = CASES["tgonGT1_nac"]
EXAMPLE = CASE.example_gene
NA = "N/A (orthology not determined for pseudogenes)"


def located(
    gene: str, organism: str, contig: str, start: int, group: str
) -> JSONObject:
    attributes: JSONObject = {
        **gene_attributes("300", "No", "protein coding gene"),
        "organism_full": organism,
        "gene_orthomcl_name": group,
        "sequence_id": contig,
        "gene_start_min": str(start),
        "gene_end_max": str(start + 899),
    }
    return record(gene, f"{gene}-t1", attributes)


def taxon(organism: str, records: list[JSONObject]) -> SearchCall:
    return SearchCall(
        record_type="transcript",
        search_name="GenesByTaxon",
        parameters={"organism": json.dumps([organism])},
        report=None,
        records=records,
        served_total=len(records) + 100,
    )


def kept(call: WireCall) -> tuple[list[str], str | None, int]:
    match call:
        case SearchCall():
            rows = [
                GeneRow.from_record(WDKRecordInstance.model_validate(raw))
                for raw in call.records
            ]
            return [row.gene for row in rows], call.kept, call.total
        case _:
            raise AssertionError(call)


def example_genome() -> SearchCall:
    groups = {3: "OGR8_3", 5: "", 6: NA}
    return taxon(
        ARI,
        [
            located(
                EXAMPLE if i == 7 else f"A{i}",
                ARI,
                "KQ1",
                1000 * i + 1,
                groups.get(i, f"OG8_{i}"),
            )
            for i in range(15)
        ]
        + [located("B1", ARI, "KQ2", 7001, "OG8_9")],
    )


def absent_genome() -> SearchCall:
    return taxon(
        GT1,
        [
            located("G2", GT1, "chrX", 50001, "OG8_2"),
            located("G0", GT1, "chrX", 60001, "OG8_0"),
            located("G3", GT1, "chrX", 70001, "OGR8_3"),
            located("G6", GT1, "chrX", 80001, NA),
            located("GW", GT1, "chrVIIb", 2001, "OG8_99"),
            located("GO", GT1, "chrVIIb", 9001, "OG8_98"),
        ],
    )


def window() -> WindowCall:
    return WindowCall(
        abbrev="tgonGT1",
        seqid="chrVIIb",
        start=1000,
        end=2999,
        served_start=1000,
        sequence="A" * 2000,
    )


def test_the_case_is_the_ari_nac_gene_missing_in_gt1() -> None:
    assert CASES == {"tgonGT1_nac": CASE}
    assert (CASE.file, CASE.site, EXAMPLE, CASE.absent_organism) == (
        "missing_tgonGT1_nac.json",
        "toxodb",
        "TGARI_257090",
        GT1,
    )


def test_trimming_keeps_the_walked_genes_their_groups_and_the_window() -> None:
    dataset = DatasetCall(ids=[EXAMPLE], dataset=7)
    calls: list[WireCall] = [dataset, absent_genome(), example_genome(), window()]

    trimmed = trim(CASE, calls)

    assert trimmed[0] == dataset
    assert trimmed[3] == window()
    assert kept(trimmed[1]) == (
        ["G2", "GW"],
        "records in the kept example genes' groups or the window",
        2,
    )
    assert kept(trimmed[2]) == (
        [f"A{i}" for i in range(1, 7)] + [EXAMPLE] + [f"A{i}" for i in range(8, 14)],
        "the example and the 6 genes on each side of it",
        13,
    )


def test_the_window_kept_is_the_anchor_window_the_check_reads_last() -> None:
    example_window = WindowCall(
        abbrev="tgonARI",
        seqid="KQ1",
        start=7001,
        end=7900,
        served_start=7001,
        sequence="A" * 900,
    )
    calls: list[WireCall] = [
        absent_genome(),
        example_genome(),
        example_window,
        window(),
    ]

    trimmed = trim(CASE, calls)

    assert kept(trimmed[0])[0] == ["G2", "GW"]
    assert trimmed[2:] == [example_window, window()]


def test_a_run_without_genome_reads_is_kept_whole() -> None:
    calls: list[WireCall] = [DatasetCall(ids=[EXAMPLE], dataset=7)]

    assert trim(CASE, calls) == calls


def test_an_untrimmed_search_serves_its_total() -> None:
    assert kept(example_genome())[1:] == (None, 116)


def test_a_recording_reads_back(tmp_path: Path) -> None:
    recorded = MissingRecording(case=CASE, calls=[window(), absent_genome()])

    write_recording(tmp_path, recorded)

    assert (
        MissingRecording.model_validate_json((tmp_path / CASE.file).read_text())
        == recorded
    )

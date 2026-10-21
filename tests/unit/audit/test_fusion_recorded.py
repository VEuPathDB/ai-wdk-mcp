import pytest
from scripts.record_audit_fusion import CASES, FusionRecording
from scripts.record_audit_missing import DatasetCall, SearchCall
from tests._support.missing_wire import FIXTURES, replay
from veupathdb.wdk import WDKAnswer

from veupathdb_mcp.audit.genes import rows_of
from veupathdb_mcp.audit.lengths import (
    LONG_ABOVE,
    MAX_SPREAD,
    SHORT_BELOW,
    call_length,
)
from veupathdb_mcp.tools.audit_fusion_tools import audit_gene_fusion

type GenomeReport = tuple[str, int, int]


def recording(case: str) -> FusionRecording:
    return FusionRecording.model_validate_json(
        (FIXTURES / CASES[case].file).read_text()
    )


def answers_of(recorded: FusionRecording, search: str) -> list[WDKAnswer]:
    answers: list[WDKAnswer] = []
    for call in recorded.calls:
        match call:
            case SearchCall(search_name=name) if name == search:
                answers.append(
                    WDKAnswer.model_validate(
                        {"meta": {"totalCount": call.total}, "records": call.records}
                    )
                )
            case _:
                pass
    return answers


def reads(recorded: FusionRecording) -> tuple[list[int], list[GenomeReport]]:
    datasets: list[int] = []
    genomes: list[GenomeReport] = []
    for call in recorded.calls:
        match call:
            case DatasetCall(ids=ids):
                datasets.append(len(ids))
            case SearchCall(search_name="GenesByTaxon"):
                genomes.append(
                    (call.parameters["organism"], len(call.records), call.served_total)
                )
            case _:
                pass
    return datasets, genomes


async def test_the_fragile_rpt6_model_holds_the_upstream_coatneyi_neighbour(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorded = recording("pfraNilgiri_rpt6")
    wire = replay(monkeypatch, recorded.calls)

    result = await audit_gene_fusion("plasmodb", "AK88_02763")

    assert (result.length_class, result.ratio) == ("LONG", 2.583)
    assert (result.organisms, result.group_median, result.group_copies) == (
        63,
        424,
        1,
    )
    assert result.reference_gene == "PCOAH_00051830"
    assert result.fusion is not None
    assert result.fusion.verdict == "EXTRA_MATCHES_NEIGHBOUR"
    assert result.fusion.extra == [(1, 220), (221, 270), (271, 690)]
    assert result.fusion.extra_windows == 66
    assert (
        result.fusion.partner,
        result.fusion.closest_neighbour,
        result.fusion.neighbour_windows,
    ) == ("PCOAH_00051820", None, 56)
    assert (result.fusion.product, result.fusion.partner_product) == (
        "26S protease regulatory subunit 8",
        "Uncharacterized protein",
    )
    assert result.fusion.neighbours == [
        "PCOAH_00051800",
        "PCOAH_00051810",
        "PCOAH_00051820",
        "PCOAH_00051840",
        "PCOAH_00051850",
        "PCOAH_00051860",
    ]
    assert (result.fusion.partner_group, result.fusion.partner_copies) == (
        "OG8_0090231",
        [],
    )
    assert wire.calls == []


def test_each_fragile_genome_report_keeps_genes_past_the_reach_and_off_the_contig() -> (
    None
):
    recorded = recording("pfraNilgiri_rpt6")
    kept = [
        sorted((row.sequence_id, row.gene) for row in rows_of(answer, "x"))
        for answer in answers_of(recorded, "GenesByTaxon")
    ]

    assert reads(recorded) == (
        [1, 63, 2, 6],
        [
            ('["Plasmodium coatneyi Hackeri"]', 10, 5575),
            ('["Plasmodium fragile strain nilgiri"]', 10, 5744),
        ],
    )
    assert kept[0][0] == ("CP016246", "PCOAH_00019760")
    assert [gene for seqid, gene in kept[0] if seqid == "CP016252"] == [
        "PCOAH_00051790",
        *(f"PCOAH_000518{n}0" for n in range(8)),
    ]
    assert kept[1][-1] == ("KQ001687", "AK88_03653")
    assert [gene for seqid, gene in kept[1] if seqid == "KQ001672"] == [
        f"AK88_027{n}" for n in range(59, 68)
    ]


async def test_the_me49_pbgs_pitrilysin_model_is_not_judged_by_its_paralog_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorded = recording("tgonME49_pbgs")
    wire = replay(monkeypatch, recorded.calls)

    result = await audit_gene_fusion("toxodb", "TGME49_500302")

    assert (result.length_class, result.ratio, result.fusion) == (
        "UNQUALIFIED",
        1.087,
        None,
    )
    assert (result.organisms, result.group_median) == (38, 1604)
    assert (result.group_copies, result.group_spread) == (2, 0.317)
    assert result.reference_gene == "LOC34617740"
    assert reads(recorded) == ([1, 86], [])
    assert wire.calls == []


def test_the_me49_pbgs_model_fails_the_spread_and_ratio_gates_too() -> None:
    [_, rows] = [
        rows_of(a, "x")
        for a in answers_of(recording("tgonME49_pbgs"), "GeneByLocusTag")
    ]
    longest = {row.organism: row for row in rows}
    for row in rows:
        if (row.protein_length or 0) > (longest[row.organism].protein_length or 0):
            longest[row.organism] = row
    pbgs = longest["Toxoplasma gondii ME49"]

    call = call_length([pbgs], list(longest.values()))

    assert (pbgs.gene, pbgs.protein_length) == ("TGME49_500302", 1743)
    assert (call.length_class, call.profile.copies) == ("UNQUALIFIED", 1)
    assert (round(call.profile.spread, 3), call.ratio) == (0.317, 1.087)
    assert call.profile.spread > MAX_SPREAD
    assert call.ratio is not None
    assert SHORT_BELOW <= call.ratio <= LONG_ABOVE

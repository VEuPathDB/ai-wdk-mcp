import pytest
from tests._support.missing_wire import recording, replay_records

from veupathdb_mcp.audit.codes import GeneticCode
from veupathdb_mcp.tools import audit_missing_tools

NAC = "missing_tgonGT1_nac.json"


async def test_the_ari_nac_gene_lies_unannotated_between_gt1_anchors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorded = recording(NAC)
    wire, _ = replay_records(monkeypatch, recorded.calls, 2)

    result = await audit_missing_tools.audit_missing_gene(
        "toxodb", "TGARI_257090", "Toxoplasma gondii GT1"
    )

    assert result.verdict == "IN_DNA_UNANNOTATED"
    assert result.anchors is not None
    left, right = result.anchors.left, result.anchors.right
    assert (left.neighbour, left.gene, left.start, left.end, left.strand) == (
        "TGARI_257070",
        "TGGT1_257070",
        4176004,
        4180213,
        "-",
    )
    assert (right.neighbour, right.gene, right.start, right.end, right.strand) == (
        "TGARI_257100",
        "TGGT1_257100",
        4153116,
        4154810,
        "+",
    )
    assert result.anchors.between == (4154810, 4176004)
    assert result.located is not None
    assert (result.located.windows, result.located.found, result.located.ns) == (
        34,
        34,
        0,
    )
    assert result.located.span == (4156680, 4157729)
    assert (result.example_length, result.overlapping) == (359, [])
    assert result.open_frame is not None
    assert (result.open_frame.length, result.open_frame.identical) == (196, 196)
    assert (result.stops, result.intact_frame) == ([163], False)
    assert (result.code, result.code_inferred) == (GeneticCode.STANDARD, True)
    assert wire.calls == []


async def test_the_recording_reads_the_window_between_the_anchors_padded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorded = recording(NAC)
    window = recorded.calls[-1]

    assert (window.kind, recorded.case.site) == ("window", "toxodb")
    assert window.model_dump(include={"abbrev", "seqid", "start", "end"}) == {
        "abbrev": "tgonGT1",
        "seqid": "TGGT1_chrVIIb",
        "start": 4151810,
        "end": 4179004,
    }

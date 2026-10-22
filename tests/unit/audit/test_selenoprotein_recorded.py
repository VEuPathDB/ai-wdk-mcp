import json

import pytest
from tests._support.audit_wire import FIXTURES
from tests._support.selenoprotein_wire import SelenoproteinWire

from veupathdb_mcp.audit.codes import GeneticCode
from veupathdb_mcp.audit.selenocysteine import check_sec_stop
from veupathdb_mcp.tools.audit_tools import audit_selenoprotein_end

GT1 = "TGGT1_316600"
ME49 = "TGME49_316600"
TRANSCRIPTS = ("GeneTranscripts",)
MODEL = ("GeneModelDump",)
STORE = "https://qa.toxodb.org/toxo.qa/service/jbrowse"
FASTA = "TgondiiGT1%2FgenomeAndProteome%2Ffasta%2Fgenome.fasta"


def region(name: str) -> dict[str, str]:
    return json.loads((FIXTURES / name).read_text())


async def test_the_recorded_gt1_selk_model_stops_at_its_sec_codon(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    served = SelenoproteinWire(monkeypatch)
    gt1, me49 = region("tgonGT1_selk.json"), region("tgonME49_selk.json")
    from_region = check_sec_stop(
        gt1["model_protein"],
        me49["reference_protein"],
        gt1["sequence"],
        "+",
        GeneticCode.STANDARD,
    )

    result = await audit_selenoprotein_end("toxodb", GT1, ME49)

    assert result.verdict == "STOPS_AT_SEC"
    assert result.after_model_end.startswith("*G*")
    assert (result.reference_tail, result.tail_identity, result.sec_aligned) == (
        "UG",
        1.0,
        True,
    )
    assert (
        result.after_model_end,
        result.reference_tail,
        result.tail_identity,
        result.sec_aligned,
    ) == (
        from_region.after_model_end,
        from_region.reference_tail,
        from_region.tail_identity,
        from_region.sec_aligned,
    )
    assert (result.gene, result.reference_gene) == (GT1, ME49)
    assert served.reports.datasets == []
    assert [(m.gene, m.strand) for m in result.models] == [(GT1, "+"), (ME49, "+")]
    last = result.models[0].cds[-1][1]
    stop = gt1["sequence"][last - 2 - int(gt1["start"]) : last + 1 - int(gt1["start"])]
    assert stop == "TGA"
    assert result.models[0].seqid == gt1["seqid"]
    assert result.models[0].cds == [
        (5359580, 5359801),
        (5360347, 5360415),
        (5361232, 5361336),
    ]
    assert result.models[1].cds == [
        (5414938, 5415159),
        (5415737, 5415805),
        (5416622, 5416732),
    ]
    assert [sum(b - a + 1 for a, b in m.cds) for m in result.models] == [
        3 * (131 + 1),
        3 * (133 + 1),
    ]


async def test_the_recorded_call_reads_the_rows_proteins_both_models_and_one_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    served = SelenoproteinWire(monkeypatch)
    wire = served.wire

    await audit_selenoprotein_end("toxodb", GT1, ME49)

    assert served.records.reads == [
        ("gene", GT1, TRANSCRIPTS),
        ("gene", ME49, TRANSCRIPTS),
        ("gene", GT1, TRANSCRIPTS),
        ("transcript", "TGGT1_316600-t26_1", ()),
        ("gene", ME49, TRANSCRIPTS),
        ("transcript", "TGME49_316600.R3814", ()),
        ("gene", GT1, MODEL),
        ("gene", ME49, MODEL),
    ]
    assert served.records.reads == [
        (r.record_type, r.primary_key["source_id"], tuple(r.tables))
        for r in wire.records
    ]
    assert served.store.served == [
        (f"{STORE}/organismSpecific/tgonGT1", ""),
        (f"{STORE}/store?data={FASTA}.fai", ""),
        (f"{STORE}/store?data={FASTA}", "bytes=53457687-53460094"),
    ]
    assert served.store.served == [(e.url, e.byte_range) for e in wire.store]
    assert {e.status for e in wire.store} <= {200, 206}
    assert {r.status for r in wire.records} == {200}
    assert served.reports.datasets == []

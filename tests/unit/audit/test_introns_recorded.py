import pytest
from tests._support.audit_wire import answers
from tests._support.intron_wire import Served, load_introns

from veupathdb_mcp.audit.codes import GeneticCode
from veupathdb_mcp.audit.introns import IntronSupport
from veupathdb_mcp.audit.introns_orthologs import OrthologSupport
from veupathdb_mcp.tools.audit_intron_tools import audit_intron_support

PKAC = "introns_pcynM_pkac.json"
DMAW = "introns_afumAf293_dmaw.json"
ATP_SITE = "GSFGRVILATYKNEDFPPVAIKRFEKSKIIKQKQVDHVFSERKILNYISHPFCVNLYGSF"


def served_length(name: str) -> int:
    [record] = answers(load_introns(name).protein_answers)[0].records
    return len((record.attribute_text("protein_sequence") or "").rstrip("*"))


async def test_the_recorded_pkac_model_misses_its_atp_site_exon(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    served = Served(monkeypatch, load_introns(PKAC))

    result = await audit_intron_support("plasmodb", "PcyM_0736700")

    assert result.verdict == "UNSUPPORTED_MISSING_EXON"
    assert result.introns == [
        IntronSupport(start=1381746, end=1382305, reads=0, tracks=0),
        IntronSupport(start=1382466, end=1382630, reads=1970, tracks=1),
        IntronSupport(start=1382791, end=1383063, reads=1442, tracks=1),
    ]
    assert result.unread is not None
    [unread] = result.unread
    assert (unread.start, unread.end, unread.in_cds, unread.outcome) == (
        1381746,
        1382305,
        True,
        "MISSING_EXON",
    )
    assert unread.replacement == [
        IntronSupport(start=1381746, end=1381886, reads=1436, tracks=1),
        IntronSupport(start=1382045, end=1382280, reads=1686, tracks=1),
    ]
    assert (result.best_junction_reads, result.tracks_refused) == (1970, [])
    assert result.unstranded_ignored == 0
    assert (result.transcript, result.other_transcripts) == ("PcyM_0736700-t36_1", 0)
    assert result.corrected_cds is not None
    assert [end - start + 1 for start, end in result.corrected_cds] == [
        124,
        158,
        185,
        160,
        399,
    ]
    assert result.corrected_cds[1] == (1381887, 1382044)
    assert result.corrected_protein is not None
    assert (served_length(PKAC), len(result.corrected_protein)) == (280, 341)
    assert ATP_SITE in result.corrected_protein
    assert (result.frame_kept, result.code, result.code_inferred) == (
        True,
        GeneticCode.STANDARD,
        True,
    )
    assert result.orthologs == OrthologSupport(
        named=60,
        read=60,
        compared=[
            "PVX_086975",
            "PVL_070027900",
            "PKNH_0733500",
            "PF3D7_0934800",
            "PBANKA_0835600",
            "PY05235",
            "PCHAS_0835900",
            "PRG01_1250200",
        ],
        for_corrected=7,
        for_annotated=0,
    )
    assert served.jbrowse.track_reads == [
        (
            "PcynomolgiM/genomeBrowser/gff/unifiedIntronJunction.gff.gz",
            "PcyM_07",
            1381422,
            1383662,
        )
    ]
    assert served.jbrowse.windows == [("pcynM", "PcyM_07", 1378622, 1386462)]
    assert served.records.reads == [["GeneModelDump"], ["Orthologs"]]
    assert [len(d.source_content.ids) for d in served.reports.datasets] == [1, 1, 60]


async def test_the_recorded_dmaw_intron_is_shifted_by_24_bases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    served = Served(monkeypatch, load_introns(DMAW))

    result = await audit_intron_support("fungidb", "Afu2g18040")

    assert result.verdict == "UNSUPPORTED_SHIFTED"
    assert result.introns == [
        IntronSupport(start=4793693, end=4793790, reads=0, tracks=0),
        IntronSupport(start=4793909, end=4793969, reads=1349, tracks=1),
    ]
    assert result.unread is not None
    [unread] = result.unread
    assert (unread.start, unread.end, unread.in_cds, unread.outcome) == (
        4793693,
        4793790,
        True,
        "SHIFTED",
    )
    assert unread.replacement == [
        IntronSupport(start=4793713, end=4793786, reads=1226, tracks=1)
    ]
    assert result.corrected_cds == [
        (4793606, 4793712),
        (4793787, 4793908),
        (4793970, 4795120),
    ]
    assert result.corrected_protein is not None
    assert (served_length(DMAW), len(result.corrected_protein)) == (451, 459)
    assert "ANLSESKV" in result.corrected_protein
    assert (result.frame_kept, result.code_inferred) == (True, True)
    assert result.orthologs is not None
    assert (result.orthologs.for_corrected, result.orthologs.for_annotated) == (0, 0)
    assert (result.orthologs.named, result.orthologs.read) == (60, 60)
    assert (result.best_junction_reads, result.transcript) == (1349, "Afu2g18040-T")
    assert result.unstranded_ignored == 0
    assert len(result.orthologs.compared) == 8
    assert served.jbrowse.windows == [
        ("afumAf293", "Chr2_A_fumigatus_Af293", 4790606, 4798120)
    ]

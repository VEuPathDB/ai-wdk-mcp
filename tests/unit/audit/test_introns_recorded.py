import pytest
from tests._support.audit_wire import answers
from tests._support.intron_wire import Served, load_introns
from tests._support.record_site import (
    RecordedRecords,
    ReplayStore,
    install_recorded_records,
    install_store,
    load_records,
)

from veupathdb_mcp.audit import introns_inputs
from veupathdb_mcp.audit.codes import GeneticCode
from veupathdb_mcp.audit.intron_coverage import (
    COVERAGE_CANDIDATE_PAIRS,
    coverage_choice,
)
from veupathdb_mcp.audit.introns import (
    IntronAudit,
    IntronSupport,
    UnreadIntron,
)
from veupathdb_mcp.audit.introns_inputs import (
    ORTHOLOG_PROTEINS_READ,
)
from veupathdb_mcp.audit.introns_orthologs import OrthologSupport
from veupathdb_mcp.tools.audit_intron_tools import audit_intron_support

PKAC = "introns_pcynM_pkac.json"
DMAW = "introns_afumAf293_dmaw.json"
PKAC_PROTEINS = "introns_pcynM_pkac_proteins.json"
DMAW_PROTEINS = "introns_afumAf293_dmaw_proteins.json"
ATP_SITE = "GSFGRVILATYKNEDFPPVAIKRFEKSKIIKQKQVDHVFSERKILNYISHPFCVNLYGSF"


def served_length(name: str) -> int:
    [record] = answers(load_introns(name).protein_answers)[0].records
    return len((record.attribute_text("protein_sequence") or "").rstrip("*"))


async def test_the_recorded_pkac_model_misses_its_atp_site_exon(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    served = Served(monkeypatch, load_introns(PKAC), PKAC_PROTEINS)

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
        named=16,
        read=16,
        compared=[
            "PVX_086975",
            "PKNH_0733500",
            "POWCR01_070036800",
            "PF3D7_0934800",
            "PBANKA_0835600",
            "Py17XNL_000801943",
            "PVPCR_0803510",
            "PCHAS_0835900",
        ],
        for_corrected=8,
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
    assert result.model is not None
    assert (result.model.seqid, result.model.strand, result.model.transcript) == (
        "PcyM_07",
        "+",
        "PcyM_0736700-t36_1",
    )
    assert result.model.cds == [
        (1381622, 1381745),
        (1382306, 1382465),
        (1382631, 1382790),
        (1383064, 1383462),
    ]
    assert result.model.exons == result.model.cds
    assert result.model.gene == "PcyM_0736700"
    assert sum(end - start + 1 for start, end in result.model.cds) == 3 * (280 + 1)
    assert served.records.reads == [["GeneModelDump"], ["Orthologs"]]
    assert served.reports.datasets == []
    assert served.rows.reads == ["PcyM_0736700"]
    assert len(served.rows.protein_reads) == 1 + ORTHOLOG_PROTEINS_READ


async def test_the_recorded_dmaw_intron_is_shifted_by_24_bases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    served = Served(monkeypatch, load_introns(DMAW), DMAW_PROTEINS)

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
    assert (result.orthologs.named, result.orthologs.read) == (16, 16)
    assert (result.best_junction_reads, result.transcript) == (1349, "Afu2g18040-T")
    assert result.unstranded_ignored == 0
    assert len(result.orthologs.compared) == 8
    assert served.jbrowse.windows == [
        ("afumAf293", "Chr2_A_fumigatus_Af293", 4790606, 4798120)
    ]
    assert result.model is not None
    assert (result.model.seqid, result.model.strand) == (
        "Chr2_A_fumigatus_Af293",
        "-",
    )
    assert result.model.cds == [
        (4793606, 4793692),
        (4793791, 4793908),
        (4793970, 4795120),
    ]
    assert served.records.reads == [["GeneModelDump"], ["Orthologs"]]
    assert served.reports.datasets == []
    assert served.rows.reads == ["Afu2g18040"]
    assert len(served.rows.protein_reads) == 1 + ORTHOLOG_PROTEINS_READ


AFU8 = "introns_afumAf293_afu8g00850.json.xz"
AGAP7279 = "introns_agamPEST_agap007279.json.xz"
TGME49 = "introns_tgonME49_tgme49_224540.json.xz"
AGAP3685 = "introns_agamPEST_agap003685.json.xz"


async def recorded_case(
    monkeypatch: pytest.MonkeyPatch, name: str, gene: str
) -> tuple[IntronAudit, RecordedRecords, ReplayStore]:
    wire = load_records(name)
    records = install_recorded_records(monkeypatch, wire)
    store = install_store(monkeypatch, wire)
    return await audit_intron_support(wire.site, gene), records, store


def stages(store: ReplayStore) -> list[str]:
    kinds = {
        "unifiedGenomicMassSpec": "peptides",
        "genome.fasta": "genome",
        "rnaseq/": "coverage",
        "bigwig": "coverage",
    }
    return sorted(
        {kind for url, _ in store.served for part, kind in kinds.items() if part in url}
    )


def protein_reads(records: RecordedRecords) -> list[str]:
    return [gene for kind, gene, _ in records.reads if kind == "transcript"]


async def test_a_replaced_intron_is_corrected_and_judged_by_orthologs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, records, store = await recorded_case(monkeypatch, AFU8, "Afu8g00850")

    assert (result.verdict, result.best_junction_reads) == (
        "UNSUPPORTED_REPLACED",
        16153,
    )
    assert result.unread == [
        UnreadIntron(
            start=202070,
            end=202266,
            in_cds=True,
            outcome="REPLACED",
            replacement=[
                IntronSupport(start=202209, end=202266, reads=18608, tracks=1)
            ],
        )
    ]
    assert result.corrected_cds == [(202062, 202208), (202267, 202401)]
    assert result.corrected_protein is not None
    assert (len(result.corrected_protein), result.frame_kept) == (93, False)
    assert (result.code, result.code_inferred) == (GeneticCode.STANDARD, True)
    assert result.orthologs == OrthologSupport(
        named=16,
        read=16,
        compared=[
            "CIMG_08074",
            "TESG_03950",
            "M_BR32_EuGene_00059721",
            "ASPVEDRAFT_67969",
            "FNAPI_10251",
            "NECHADRAFT_76575",
            "I7I53_02339",
            "I303_08007",
        ],
        for_corrected=0,
        for_annotated=8,
    )
    assert stages(store) == ["genome"]
    assert len(protein_reads(records)) == 1 + ORTHOLOG_PROTEINS_READ


async def test_an_intron_over_an_assembly_gap_is_left_unexplained(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, records, store = await recorded_case(monkeypatch, AGAP7279, "AGAP007279")

    assert result.verdict == "UNSUPPORTED_UNEXPLAINED"
    assert result.unread == [
        UnreadIntron(
            start=44981063,
            end=44981393,
            in_cds=True,
            outcome="UNEXPLAINED",
            replacement=[],
        )
    ]
    assert result.evidence_unread == [
        "the intron 44981063-44981393 spans an assembly gap"
    ]
    assert (result.corrected_cds, result.orthologs) == (None, None)
    assert stages(store) == ["genome", "peptides"]
    assert protein_reads(records) == []


async def test_a_peptide_spanned_intron_is_supported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, records, store = await recorded_case(monkeypatch, TGME49, "TGME49_224540")

    assert (result.verdict, result.unread) == ("SUPPORTED", [])
    assert result.introns is not None
    assert IntronSupport(start=2993548, end=2995140, reads=0, tracks=0) in (
        result.introns
    )
    assert (result.corrected_cds, result.orthologs, result.evidence_unread) == (
        None,
        None,
        [],
    )
    assert stages(store) == ["peptides"]
    assert records.reads == [
        ("gene", "TGME49_224540", ("GeneTranscripts",)),
        ("gene", "TGME49_224540", ("GeneModelDump",)),
    ]


SHORTLIST = [
    "salivary glands paired-end (unique forward)",
    "salivary glands paired-end (unique reverse)",
    "E-MTAB-2880:E_20h_F (unique forward)",
    "E-MTAB-2880:E_20h_F (unique reverse)",
    "midguts paired-end (unique forward)",
    "midguts paired-end (unique reverse)",
]


async def test_a_covered_unspliced_intron_is_retained(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, records, store = await recorded_case(monkeypatch, AGAP3685, "AGAP003685")
    choice = await coverage_choice(
        introns_inputs.get_jbrowse_client("vectorbase"), "agamPEST"
    )

    assert [sub.name for sub in choice.candidates] == SHORTLIST
    assert result.verdict == "UNSUPPORTED_RETAINED"
    assert result.unread is not None
    [unread] = result.unread
    assert (unread.start, unread.end, unread.outcome, unread.motif) == (
        41952076,
        41952160,
        "RETAINED",
        "GT..AG",
    )
    assert unread.depth is not None
    assert unread.depth.track == "E-MTAB-2880:E_20h_F (unique reverse)"
    assert (
        round(unread.depth.intron_median_depth, 2),
        round(unread.depth.exon_median_depth, 2),
        unread.depth.covered_share,
        unread.depth.depth_share,
    ) == (4.17, 7.83, 0.988, 0.533)
    assert result.corrected_cds == [
        (41952051, 41952902),
        (41953562, 41953639),
        (41953733, 41953990),
        (41954090, 41954101),
    ]
    assert result.corrected_protein is not None
    assert (len(result.corrected_protein), result.frame_kept) == (399, False)
    assert result.orthologs is not None
    assert (
        result.orthologs.named,
        result.orthologs.read,
        result.orthologs.for_corrected,
        result.orthologs.for_annotated,
    ) == (16, 16, 3, 2)
    headers = [url for url, read in store.served if read == "bytes=0-343"]
    depth_files = {
        url for url, read in store.served if "bigwig" in url and read != "bytes=0-343"
    }
    assert (len(headers), len(set(headers))) == (168, 168)
    assert len(depth_files) == 2 * COVERAGE_CANDIDATE_PAIRS
    assert result.evidence_unread == []
    assert len(protein_reads(records)) == 1 + ORTHOLOG_PROTEINS_READ

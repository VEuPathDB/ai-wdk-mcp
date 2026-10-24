import httpx
import pytest
from pydantic import ValidationError
from tests._support.intron_genes import E1, E2, E3, E4, I1, I2, I3, SPLICED, dna
from tests._support.intron_site import (
    GENE,
    OTHER_TRACK,
    READS,
    TRACK,
    Site,
    junctions,
    model_rows,
)
from tests._support.site_failures import answering, raised, wdk_read
from veupathdb.errors import DataParsingError
from veupathdb.jbrowse import GenomeWindow, JBrowseError

from veupathdb_mcp.audit.codes import GeneticCode
from veupathdb_mcp.audit.introns import IntronAudit, IntronSupport, UnreadIntron
from veupathdb_mcp.audit.introns_orthologs import OrthologSupport
from veupathdb_mcp.tools.audit_intron_tools import audit_intron_support

WHOLE = (I1[0], I2[1])


async def test_a_hidden_exon_is_served_with_its_corrected_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = Site(monkeypatch)
    jbrowse = junctions(monkeypatch, READS)

    result = await audit_intron_support("plasmodb", GENE)

    assert result.verdict == "UNSUPPORTED_MISSING_EXON"
    assert result.unread == [
        UnreadIntron(
            start=1151,
            end=1360,
            in_cds=True,
            outcome="MISSING_EXON",
            replacement=[
                IntronSupport(start=1151, end=1210, reads=100, tracks=1),
                IntronSupport(start=1301, end=1360, reads=120, tracks=1),
            ],
        )
    ]
    assert result.corrected_cds == [E1, E2, E3, E4]
    assert result.corrected_exons == [E1, E2, E3, E4]
    assert result.corrected_protein == SPLICED
    assert (result.gene, result.transcript, result.other_transcripts) == (
        GENE,
        f"{GENE}-t1",
        0,
    )
    assert (result.code, result.code_inferred) == (GeneticCode.STANDARD, True)
    assert (result.best_junction_reads, result.tracks_refused) == (300, [])
    assert result.orthologs == OrthologSupport(
        named=2, read=2, compared=["PKNH_1", "PVX_1"], for_corrected=2, for_annotated=0
    )
    assert jbrowse.abbrevs == ["pcynX"]
    assert jbrowse.track_reads == [(TRACK, "contig", 861, 1803)]
    assert jbrowse.windows == [("pcynX", "contig", 1, 4603)]
    assert site.records_read == [["GeneModelDump"]]
    assert site.proteins_read == [GENE, "PVX_1", "PKNH_1"]
    assert (jbrowse.lists, result.evidence_unread) == ([], [])
    assert site.tables_read == [GENE]


async def test_an_audit_whose_corrected_cds_leaves_its_exons_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    Site(monkeypatch)
    junctions(monkeypatch, READS)
    served = (await audit_intron_support("plasmodb", GENE)).model_dump()

    with pytest.raises(ValidationError, match="lies inside its exons"):
        IntronAudit.model_validate(
            {**served, "corrected_exons": [E1, E2, E3, (E4[0], E4[1] - 3)]}
        )
    assert IntronAudit.model_validate({**served, "corrected_exons": None}) == (
        IntronAudit.model_validate(served).model_copy(update={"corrected_exons": None})
    )


async def test_the_served_check_is_camel_case(monkeypatch: pytest.MonkeyPatch) -> None:
    Site(monkeypatch)
    junctions(monkeypatch, READS)

    result = await audit_intron_support("plasmodb", GENE)

    dumped = result.model_dump(by_alias=True)
    assert {
        "correctedCds",
        "correctedExons",
        "correctedProtein",
        "frameKept",
        "codeInferred",
        "bestJunctionReads",
        "otherTranscripts",
        "tracksRefused",
        "unstrandedIgnored",
    } <= set(dumped)
    assert dumped["unread"][0]["inCds"] is True
    assert dumped["orthologs"] == {
        "named": 2,
        "read": 2,
        "compared": ["PKNH_1", "PVX_1"],
        "forCorrected": 2,
        "forAnnotated": 0,
        "reason": None,
    }


async def test_two_unread_introns_are_corrected_together(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = Site(monkeypatch)
    site.model = model_rows([E1, (1235, E2[1]), (1385, E3[1]), E4], ("CDS", "Exon"))
    site.proteins[GENE] = SPLICED[:30] + SPLICED[38:60] + SPLICED[68:]
    junctions(monkeypatch, {I1: 60, I2: 900, I3: 300})

    result = await audit_intron_support("plasmodb", GENE)

    assert result.verdict == "UNSUPPORTED_SHIFTED"
    assert result.unread is not None
    assert [(u.start, u.end, u.outcome) for u in result.unread] == [
        (1151, 1234, "SHIFTED"),
        (1301, 1384, "SHIFTED"),
    ]
    assert result.corrected_protein == SPLICED
    assert result.code_inferred


async def test_only_the_longest_cds_transcript_is_judged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = Site(monkeypatch)
    site.model = [
        *model_rows([E1, E3, E4], ("CDS", "Exon")),
        *model_rows([E1, E4], ("CDS", "Exon"), transcript=f"{GENE}-t2"),
    ]
    junctions(monkeypatch, READS)

    result = await audit_intron_support("plasmodb", GENE)

    assert (result.transcript, result.other_transcripts) == (f"{GENE}-t1", 1)
    assert result.introns is not None
    assert [(i.start, i.end) for i in result.introns] == [WHOLE, I3]
    assert result.model is not None
    assert (result.model.transcript, result.model.cds) == (f"{GENE}-t1", [E1, E3, E4])
    assert (result.model.seqid, result.model.strand) == ("contig", "+")


async def test_a_model_on_two_strands_is_judged_and_not_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = Site(monkeypatch)
    [first, *rest] = model_rows([E1, E3, E4], ("Exon",))
    site.model = [
        *model_rows([E1, E3, E4], ("CDS",)),
        {**first, "strand": "-"},
        *rest,
    ]
    junctions(monkeypatch, READS)

    result = await audit_intron_support("plasmodb", GENE)

    assert result.verdict == "UNSUPPORTED_MISSING_EXON"
    assert result.corrected_cds == [E1, E2, E3, E4]
    assert result.model is None
    assert result.evidence_unread == [
        f"the GeneModelDump rows of {GENE} lie on more than one strand or sequence"
    ]


async def test_a_supported_gene_reads_no_genome_protein_or_ortholog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = Site(monkeypatch)
    site.model = model_rows([E1, E2, E3, E4], ("CDS", "Exon"))
    jbrowse = junctions(monkeypatch, READS)

    result = await audit_intron_support("plasmodb", GENE)

    assert result.verdict == "SUPPORTED"
    assert (result.code, result.code_inferred, result.orthologs) == (None, False, None)
    assert (site.tables_read, site.proteins_read, jbrowse.windows) == ([], [], [])


async def test_an_unexplained_gene_reads_its_evidence_and_serves_no_correction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = Site(monkeypatch)
    jbrowse = junctions(monkeypatch, {I3: 300})

    result = await audit_intron_support("plasmodb", GENE)

    assert result.verdict == "UNSUPPORTED_UNEXPLAINED"
    assert result.unread is not None
    assert [(u.outcome, u.motif, u.depth) for u in result.unread] == [
        ("UNEXPLAINED", "GT..AG", None)
    ]
    assert (result.corrected_cds, result.corrected_protein, result.code) == (
        None,
        None,
        None,
    )
    assert jbrowse.lists == [("organismSpecific", "pcynX"), ("rnaseq", "pcynX")]
    assert result.evidence_unread == [
        "pcynX lists no unifiedGenomicMassSpec track",
        "pcynX lists no RNA-seq coverage track",
    ]
    assert (site.proteins_read, jbrowse.windows) == (
        [],
        [("pcynX", "contig", 1, 4603)],
    )


async def test_a_not_expressed_gene_carries_its_best_junction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    Site(monkeypatch)
    junctions(monkeypatch, {I1: 30, I3: 49})

    result = await audit_intron_support("plasmodb", GENE)

    assert (result.verdict, result.best_junction_reads) == ("NOT_EXPRESSED", 49)
    assert result.unread is None


async def test_a_track_that_does_not_index_the_sequence_is_named(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    Site(monkeypatch)
    jbrowse = junctions(
        monkeypatch, READS, paths=(OTHER_TRACK, TRACK), indexed=(TRACK,)
    )

    result = await audit_intron_support("plasmodb", GENE)

    assert result.verdict == "UNSUPPORTED_MISSING_EXON"
    assert result.tracks_refused == [
        f"the index of {OTHER_TRACK} names no sequence contig"
    ]
    assert [read[0] for read in jbrowse.track_reads] == [OTHER_TRACK, TRACK]


@pytest.mark.parametrize(
    ("refusal", "reason"),
    [
        (
            DataParsingError("the gene record of PcyX_1 gives no readable Orthologs"),
            "the gene record of PcyX_1 gives no readable Orthologs",
        ),
        (
            httpx.ReadTimeout("timed out"),
            "plasmodb did not answer the ortholog reads: ReadTimeout timed out",
        ),
    ],
)
async def test_a_failed_ortholog_read_keeps_the_correction(
    monkeypatch: pytest.MonkeyPatch, refusal: Exception, reason: str
) -> None:
    site = Site(monkeypatch)
    site.table_refusal = refusal
    junctions(monkeypatch, READS)

    result = await audit_intron_support("plasmodb", GENE)

    assert (result.verdict, result.corrected_protein) == (
        "UNSUPPORTED_MISSING_EXON",
        SPLICED,
    )
    assert result.orthologs == OrthologSupport.not_read(reason)


async def test_an_ortholog_read_the_site_refuses_names_its_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = Site(monkeypatch)
    site.table_refusal = await raised(wdk_read(answering(502)))
    junctions(monkeypatch, READS)

    result = await audit_intron_support("plasmodb", GENE)

    assert result.corrected_protein == SPLICED
    assert result.orthologs is not None
    assert result.orthologs.reason is not None
    assert result.orthologs.reason.startswith(
        "plasmodb answered 502 to the ortholog reads: Request failed after retries"
    )


async def test_a_residual_group_serves_no_ortholog_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = Site(monkeypatch)
    site.row = site.row.model_copy(update={"ortholog_group": "OGR8_0001234"})
    junctions(monkeypatch, READS)

    result = await audit_intron_support("plasmodb", GENE)

    assert result.corrected_protein == SPLICED
    assert result.orthologs == OrthologSupport.not_read(
        "the ortholog group OGR8_0001234 of PcyX_1 is not an orthology group"
    )
    assert site.tables_read == []


async def test_a_label_that_is_no_orthology_group_serves_no_ortholog_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = Site(monkeypatch)
    site.row = site.row.model_copy(
        update={"ortholog_group": "N/A (orthology not determined for pseudogenes)"}
    )
    junctions(monkeypatch, READS)

    result = await audit_intron_support("plasmodb", GENE)

    assert result.corrected_protein == SPLICED
    assert result.orthologs == OrthologSupport.not_read(
        "the ortholog group N/A (orthology not determined for pseudogenes) of PcyX_1 is not an orthology group"
    )
    assert site.tables_read == []


def with_intron(bases: str) -> GenomeWindow:
    window = dna()
    first = I2[0] - window.start
    sequence = window.sequence[:first] + bases + window.sequence[first + len(bases) :]
    return GenomeWindow(seqid=window.seqid, start=window.start, sequence=sequence)


async def test_an_intron_over_an_assembly_gap_reads_no_motif_and_is_not_corrected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = Site(monkeypatch)
    site.model = model_rows([E1, E2, E3, E4], ("CDS", "Exon"))
    jbrowse = junctions(monkeypatch, {I1: 100, I3: 300})
    jbrowse.window_served = with_intron("N" * (I2[1] - I2[0] + 1))

    result = await audit_intron_support("plasmodb", GENE)

    assert result.verdict == "UNSUPPORTED_UNEXPLAINED"
    assert result.unread is not None
    assert [(u.outcome, u.motif, u.depth) for u in result.unread] == [
        ("UNEXPLAINED", None, None)
    ]
    assert result.evidence_unread == [
        "pcynX lists no unifiedGenomicMassSpec track",
        f"the intron {I2[0]}-{I2[1]} spans an assembly gap",
    ]
    assert jbrowse.lists == [("organismSpecific", "pcynX")]
    assert (result.corrected_cds, site.proteins_read) == (None, [])


async def test_a_donor_neither_gt_nor_gc_is_noncanonical_and_read_as_exon(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = Site(monkeypatch)
    site.model = model_rows([E1, E2, E3, E4], ("CDS", "Exon"))
    site.proteins[GENE] = SPLICED
    jbrowse = junctions(monkeypatch, {I1: 100, I3: 300})
    jbrowse.window_served = with_intron("AT" + "C" * 56 + "AC")

    result = await audit_intron_support("plasmodb", GENE)

    assert result.verdict == "UNSUPPORTED_NONCANONICAL"
    assert result.unread is not None
    assert [(u.outcome, u.motif) for u in result.unread] == [("NONCANONICAL", "AT..AC")]
    assert result.corrected_cds == [E1, (E2[0], E3[1]), E4]
    assert result.corrected_exons == [E1, (E2[0], E3[1]), E4]
    assert result.corrected_protein == (
        SPLICED[:60] + "I" + "P" * 18 + "H" + SPLICED[60:]
    )
    assert result.frame_kept is True


async def test_a_genome_window_the_site_refuses_leaves_the_motif_unread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = Site(monkeypatch)
    site.model = model_rows([E1, E2, E3, E4], ("CDS", "Exon"))
    jbrowse = junctions(monkeypatch, {I1: 100, I3: 300})
    jbrowse.window_refusal = JBrowseError("GET", "https://qa.example/genome", 503)

    result = await audit_intron_support("plasmodb", GENE)

    assert result.verdict == "UNSUPPORTED_UNEXPLAINED"
    assert result.unread is not None
    assert [(u.outcome, u.motif) for u in result.unread] == [("UNEXPLAINED", None)]
    assert result.evidence_unread == [
        "pcynX lists no unifiedGenomicMassSpec track",
        "the genome window read failed: GET https://qa.example/genome answered 503",
        "pcynX lists no RNA-seq coverage track",
    ]

import re

import httpx
import pytest
from fastmcp.exceptions import ToolError
from tests._support.audit_site import window_refused
from tests._support.intron_genes import E1, E3, E4, I1, I2, I3, dna
from tests._support.intron_site import (
    ANNOTATED,
    GENE,
    READS,
    TRACK,
    JBrowse,
    Site,
    gff_line,
    junctions,
    model_rows,
    ortholog_row,
    track_list,
)
from tests._support.proteins import row
from veupathdb.jbrowse import GenomeWindow, TrackReadError

from veupathdb_mcp.audit import (
    JUNCTION_TRACKS_READ,
    JunctionTracks,
    served,
    track_reads,
)
from veupathdb_mcp.audit.codes import GeneticCode
from veupathdb_mcp.audit.genes import OrthologGroup
from veupathdb_mcp.audit.introns import IntronAudit
from veupathdb_mcp.audit.introns_inputs import (
    INTRON_READ_THROUGH,
    ortholog_choice,
)
from veupathdb_mcp.tools.audit_intron_tools import audit_intron_support


async def test_a_sequence_the_junction_index_does_not_name_is_not_checked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = Site(monkeypatch)
    jbrowse = junctions(monkeypatch, READS, indexed=())

    result = await audit_intron_support("plasmodb", GENE)

    assert result.verdict == "NOT_CHECKED"
    assert result.reason == f"the index of {TRACK} names no sequence contig"
    assert result.tracks_refused == [f"the index of {TRACK} names no sequence contig"]
    assert (result.introns, result.unread) == (None, None)
    assert (result.best_junction_reads, result.code) == (None, None)
    assert (result.transcript, result.other_transcripts) == (f"{GENE}-t1", 0)
    assert (result.orthologs, result.code_inferred) == (None, False)
    assert (jbrowse.windows, site.proteins_read) == ([], [])
    assert result.model is None


async def test_an_organism_with_no_junction_track_is_not_checked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    Site(monkeypatch)
    jbrowse = junctions(monkeypatch, READS, paths=())

    result = await audit_intron_support("plasmodb", GENE)

    assert result.verdict == "NOT_CHECKED"
    assert result.reason == "plasmodb lists no RNA-seq junction track for pcynX"
    assert (result.tracks_refused, result.introns) == (None, None)
    assert result.junction_tracks == JunctionTracks(
        organism_abbrev="pcynX", listed=0, read=0
    )
    assert jbrowse.track_reads == []


async def test_a_gene_with_one_exon_is_not_checked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = Site(monkeypatch)
    site.model = model_rows([(E1[0], E4[1])], ("CDS", "Exon"))
    jbrowse = junctions(monkeypatch, READS)

    result = await audit_intron_support("plasmodb", GENE)

    assert result.verdict == "NOT_CHECKED"
    assert result.reason == f"{GENE} has no annotated intron on plasmodb"
    assert result.transcript == f"{GENE}-t1"
    assert result.junction_tracks is None
    assert jbrowse.abbrevs == []


async def test_a_gene_with_no_cds_is_not_checked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = Site(monkeypatch)
    site.model = model_rows([E1, E3, E4], ("Exon",))
    junctions(monkeypatch, READS)

    result = await audit_intron_support("plasmodb", GENE)

    assert result.verdict == "NOT_CHECKED"
    assert result.reason == f"{GENE} has no CDS in its gene model on plasmodb"
    assert (result.transcript, result.other_transcripts) == (None, None)


async def test_unstranded_junctions_over_the_gene_leave_it_unchecked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    Site(monkeypatch)
    JBrowse(
        monkeypatch,
        track_list(TRACK),
        {(TRACK, "contig"): [gff_line("contig", I1, 100, strand=".")]},
        dna(),
    )

    result = await audit_intron_support("plasmodb", GENE)

    assert result.verdict == "NOT_CHECKED"
    assert result.reason == f"every junction over {GENE}-t1 is unstranded (1 junctions)"
    assert result.transcript == f"{GENE}-t1"


async def test_a_protein_no_code_explains_is_read_with_the_standard_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = Site(monkeypatch)
    site.proteins[GENE] = "M" + ANNOTATED[2:]
    junctions(monkeypatch, READS)

    result = await audit_intron_support("plasmodb", GENE)

    assert (result.code, result.code_inferred) == (GeneticCode.STANDARD, False)


async def test_a_window_at_the_limit_is_read(monkeypatch: pytest.MonkeyPatch) -> None:
    end = E1[0] + served.AUDIT_MAX_WINDOW_BASES - 2 * INTRON_READ_THROUGH - 1
    site = Site(monkeypatch, end=end)
    jbrowse = junctions(monkeypatch, READS)

    await audit_intron_support("plasmodb", GENE)

    assert site.records_read == [["GeneModelDump"]]
    assert jbrowse.abbrevs == ["pcynX"]


async def test_a_window_over_the_limit_is_refused_before_any_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    end = E1[0] + served.AUDIT_MAX_WINDOW_BASES - 2 * INTRON_READ_THROUGH
    site = Site(monkeypatch, end=end)
    jbrowse = junctions(monkeypatch, READS)

    with pytest.raises(
        ToolError, match=window_refused(GENE, served.AUDIT_MAX_WINDOW_BASES + 1)
    ):
        await audit_intron_support("plasmodb", GENE)

    assert (site.records_read, jbrowse.abbrevs) == ([], [])


async def test_an_unknown_gene_is_a_tool_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    Site(monkeypatch)
    junctions(monkeypatch, READS)

    with pytest.raises(ToolError, match="PcyX_9 names no gene of plasmodb"):
        await audit_intron_support("plasmodb", "PcyX_9")


def uncorrected(result: IntronAudit) -> tuple[object, ...]:
    return (
        result.corrected_cds,
        result.corrected_protein,
        result.frame_kept,
        result.code,
        result.code_inferred,
        result.orthologs,
    )


async def test_a_gene_with_no_protein_keeps_its_judgement_and_names_why(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = Site(monkeypatch)
    del site.proteins[GENE]
    junctions(monkeypatch, READS)

    result = await audit_intron_support("plasmodb", GENE)

    assert result.verdict == "UNSUPPORTED_MISSING_EXON"
    assert result.correction_reason == f"{GENE} has no protein on plasmodb"
    assert uncorrected(result) == (None, None, None, None, False, None)


async def test_a_genome_window_the_site_does_not_serve_keeps_the_judgement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    Site(monkeypatch)
    jbrowse = junctions(monkeypatch, READS)

    async def silent(*args: object) -> GenomeWindow:
        reason = "read timed out"
        raise httpx.ReadTimeout(reason)

    monkeypatch.setattr(jbrowse, "window", silent)

    result = await audit_intron_support("plasmodb", GENE)

    assert result.verdict == "UNSUPPORTED_MISSING_EXON"
    assert result.correction_reason == (
        "plasmodb did not answer the correction reads: ReadTimeout read timed out"
    )
    assert uncorrected(result) == (None, None, None, None, False, None)


async def test_an_unreadable_track_is_a_tool_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    Site(monkeypatch)
    jbrowse = junctions(monkeypatch, READS)

    async def unreadable(*args: object) -> list[str]:
        msg = "contig:861-1803 spans 17000000 compressed bytes"
        raise TrackReadError(msg)

    monkeypatch.setattr(jbrowse, "lines", unreadable)

    with pytest.raises(ToolError, match=re.escape("spans 17000000 compressed")):
        await audit_intron_support("plasmodb", GENE)


async def test_a_junction_with_no_read_count_is_a_tool_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    Site(monkeypatch)
    JBrowse(
        monkeypatch,
        track_list(TRACK),
        {(TRACK, "contig"): ["contig\tV\tintronJunction\t1151\t1360\t.\t+\t.\tID=a"]},
        dna(),
    )

    with pytest.raises(ToolError, match=f"a junction of {TRACK} gives no readable"):
        await audit_intron_support("plasmodb", GENE)


async def test_a_model_with_no_exon_row_is_a_tool_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = Site(monkeypatch)
    site.model = model_rows([E1, E3, E4], ("CDS",))
    junctions(monkeypatch, {I1: 100, I2: 120, I3: 300})

    with pytest.raises(ToolError, match=f"gives no Exon row for {GENE}-t1"):
        await audit_intron_support("plasmodb", GENE)


async def test_a_model_reaching_past_the_gene_is_a_tool_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    Site(monkeypatch, end=E4[1] - 10)
    junctions(monkeypatch, {I1: 100, I2: 120, I3: 300})

    with pytest.raises(ToolError, match=f"the model of {GENE} has a part outside"):
        await audit_intron_support("plasmodb", GENE)


async def test_a_window_that_misses_the_transcript_keeps_the_judgement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    Site(monkeypatch)
    JBrowse(
        monkeypatch,
        track_list(TRACK),
        {(TRACK, "contig"): [gff_line("contig", s, n) for s, n in READS.items()]},
        GenomeWindow(seqid="contig", start=1100, sequence="ACGT" * 100),
    )

    result = await audit_intron_support("plasmodb", GENE)

    assert result.verdict == "UNSUPPORTED_MISSING_EXON"
    assert result.correction_reason is not None
    assert "PcyX_1-t1 lies outside the window" in result.correction_reason
    assert uncorrected(result) == (None, None, None, None, False, None)


async def test_one_tabix_reader_serves_every_audit_on_one_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    Site(monkeypatch)
    jbrowse = junctions(monkeypatch, READS)
    built: list[JBrowse] = []

    def reader(client: JBrowse) -> JBrowse:
        built.append(client)
        return client

    monkeypatch.setattr(track_reads, "TabixReader", reader)

    await audit_intron_support("plasmodb", GENE)
    await audit_intron_support("plasmodb", GENE)

    assert built == [jbrowse]
    assert len(jbrowse.track_reads) == 2


async def test_past_four_junction_tracks_the_first_four_are_read_and_named(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    Site(monkeypatch)
    paths = tuple(f"PcynomolgiX/genomeBrowser/gff/junction{n}.gff.gz" for n in range(5))
    jbrowse = junctions(monkeypatch, READS, paths=paths, indexed=paths)

    result = await audit_intron_support("plasmodb", GENE)

    assert [read[0] for read in jbrowse.track_reads] == list(
        paths[:JUNCTION_TRACKS_READ]
    )
    assert result.junction_tracks == JunctionTracks(
        organism_abbrev="pcynX", listed=5, read=JUNCTION_TRACKS_READ
    )
    assert result.junction_tracks.cap_note == (
        "pcynX lists 5 junction tracks; the first 4 were read"
    )
    assert result.evidence_unread[0] == result.junction_tracks.cap_note


async def test_tracks_within_the_cap_are_all_read_and_name_no_cut(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    Site(monkeypatch)
    junctions(monkeypatch, READS)

    result = await audit_intron_support("plasmodb", GENE)

    assert result.junction_tracks == JunctionTracks(
        organism_abbrev="pcynX", listed=1, read=1
    )
    assert result.junction_tracks.cap_note is None


async def test_an_organism_past_the_cap_whose_tracks_all_refuse_names_the_cut(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    Site(monkeypatch)
    paths = tuple(f"PcynomolgiX/genomeBrowser/gff/junction{n}.gff.gz" for n in range(6))
    junctions(monkeypatch, READS, paths=paths, indexed=())

    result = await audit_intron_support("plasmodb", GENE)

    assert result.verdict == "NOT_CHECKED"
    assert result.junction_tracks == JunctionTracks(
        organism_abbrev="pcynX", listed=6, read=JUNCTION_TRACKS_READ
    )
    assert result.evidence_unread == [
        "pcynX lists 6 junction tracks; the first 4 were read"
    ]


def test_a_track_record_reads_no_more_than_it_lists() -> None:
    with pytest.raises(ValueError, match="cannot read 6"):
        JunctionTracks(organism_abbrev="pcynX", listed=5, read=6)


def test_a_track_record_built_under_a_larger_cap_still_validates() -> None:
    tracks = JunctionTracks(organism_abbrev="pcynX", listed=6, read=6)
    assert tracks.cap_note is None


def test_a_cut_note_speaks_from_the_record_alone() -> None:
    tracks = JunctionTracks(organism_abbrev="pcynX", listed=9, read=6)
    assert tracks.cap_note == "pcynX lists 9 junction tracks; the first 6 were read"


async def test_an_audit_whose_unread_list_omits_the_cut_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    Site(monkeypatch)
    paths = tuple(f"PcynomolgiX/genomeBrowser/gff/junction{n}.gff.gz" for n in range(5))
    junctions(monkeypatch, READS, paths=paths, indexed=paths)
    result = await audit_intron_support("plasmodb", GENE)

    with pytest.raises(ValueError, match="names its junction track cut"):
        IntronAudit.model_validate({**result.model_dump(), "evidence_unread": []})


def test_an_ortholog_with_no_protein_is_never_chosen_for_a_species() -> None:
    gene = row("PcyX_1", "Plasmodium cynomolgi strain X", 400)
    group = OrthologGroup(
        gene=gene.gene,
        members=[
            ortholog_row("PF3D7_1", "Plasmodium falciparum 3D7", None, "yes"),
            ortholog_row("PfDd2_1", "Plasmodium falciparum Dd2", 380),
            ortholog_row("PfIT_1", "Plasmodium falciparum IT", 410),
            ortholog_row("PY_1", "Plasmodium yoelii 17X", None),
        ],
    )

    assert ortholog_choice(group, gene) == {"PfIT_1": "Plasmodium falciparum"}

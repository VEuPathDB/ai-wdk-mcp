import pytest
from scripts.record_audit_strain import StrainWire
from tests._support.audit_site import Genome, members
from tests._support.audit_wire import (
    FIXTURES,
    answers,
    install_genome,
    install_records,
)
from tests._support.row_reads import RowReads, serve_recorded_rows
from tests._support.strain_site import Annotation, install_annotation
from tests._support.wdk_genes import ReportSite, serve_private

from veupathdb_mcp.audit import annotated_genes
from veupathdb_mcp.audit.codes import GeneticCode
from veupathdb_mcp.audit.genes import rows_of
from veupathdb_mcp.audit.lengths import GroupProfile
from veupathdb_mcp.audit.strain import Relative
from veupathdb_mcp.tools.audit_strain_tools import audit_strain_model


def install(
    monkeypatch: pytest.MonkeyPatch, name: str, abbrev: str, seqid: str
) -> tuple[StrainWire, Genome, ReportSite, RowReads, Annotation]:
    wire = StrainWire.model_validate_json((FIXTURES / name).read_text())
    install_records(monkeypatch, wire)
    genome = install_genome(monkeypatch, wire, abbrev, seqid)
    rows = serve_recorded_rows(
        monkeypatch, [*wire.gene_answers, *wire.row_answers], wire.protein_answers
    )
    _, reports = serve_private(monkeypatch, [])
    return wire, genome, reports, rows, install_annotation(monkeypatch, wire.annotation)


async def test_the_recorded_pkac_strain_model_misses_an_exon_its_genome_encodes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wire, genome, reports, rows, annotation = install(
        monkeypatch, "strain_pcynM_pkac.json", "pcynM", "PcyM_07"
    )

    result = await audit_strain_model("plasmodb", "PcyM_0736700", "PCYB_074210")

    assert (result.strain_length, result.reference_length) == (280, 341)
    assert (result.lost, result.extra) == ([(41, 100)], [])
    assert result.dna.verdict == "GENOME_ENCODES"
    assert result.dna.counts == {"model": 27, "genome_same_strand": 5, "weak": 1}
    assert result.dna.track == "MMMMGGGGGw" + "M" * 23
    assert (result.dna.ns_in_window, result.dna.at_contig_edge) == (0, False)
    assert (result.code, result.code_inferred) == (GeneticCode.STANDARD, True)
    assert (result.not_read, result.nearby_paralogs) == (None, [])
    assert (result.side, result.relatives.median) == ("NO_RELATIVES", None)
    assert (result.relatives.missing, result.relatives.copies_per_organism) == (
        "PARALOGS",
        8,
    )
    assert genome.windows == [("pcynM", "PcyM_07", 1375622, 1389462)]
    assert reports.datasets == []
    assert rows.protein_reads == ["PcyM_0736700", "PCYB_074210"]
    assert rows.reads == ["PcyM_0736700", "PCYB_074210"]
    assert annotation.lists == ["pcynM"]
    assert annotation.reads == [("PcyM_07", 1375622, 1389462)]
    assert wire.reference == "PCYB_074210"


async def test_the_recorded_pkac_paralogs_of_strain_m_lie_on_other_chromosomes() -> (
    None
):
    wire = StrainWire.model_validate_json(
        (FIXTURES / "strain_pcynM_pkac.json").read_text()
    )
    rows = [r for a in answers(wire.row_answers) for r in rows_of(a, "x")]
    strain_m = [r for r in rows if r.organism == "Plasmodium cynomolgi strain M"]

    profile = GroupProfile.of([], members(rows))

    assert (profile.organisms, profile.median, profile.copies) == (63, 4008, 8)
    assert sorted(r.sequence_id for r in strain_m if r.gene != wire.gene) == [
        "PcyM_04",
        "PcyM_08",
        "PcyM_09",
        "PcyM_11",
        "PcyM_11",
        "PcyM_13",
        "PcyM_14",
    ]


async def test_the_recorded_dd2_yip1_lost_segment_is_encoded_but_relatives_split(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wire, genome, reports, rows, annotation = install(
        monkeypatch, "strain_pfalDd2_yip1.json", "pfalDd2", "PfDd2_14"
    )

    result = await audit_strain_model("plasmodb", wire.gene, "PF3D7_1472100")

    assert wire.gene == "PfDd2_140076300"
    assert (result.strain_length, result.reference_length) == (289, 314)
    assert (result.lost, result.extra) == ([(271, 310)], [])
    assert result.dna.verdict == "GENOME_ENCODES"
    assert result.dna.counts == {"model": 27, "genome_same_strand": 3}
    assert result.dna.track == "M" * 27 + "GGG"
    assert (result.code, result.code_inferred) == (GeneticCode.STANDARD, True)
    assert (result.side, result.relatives.median) == ("UNCLEAR", 309)
    assert (result.relatives.tier, len(result.relatives.members)) == (
        "SAME_GENUS",
        40,
    )
    assert result.relatives.members[0] == Relative(
        organism="Plasmodium adleri G01", length=320
    )
    assert genome.windows == [("pfalDd2", "PfDd2_14", 2913589, 2927032)]
    assert annotation.reads == []
    assert reports.datasets == []
    assert rows.protein_reads == [wire.gene, "PF3D7_1472100"]


def test_the_recorded_pkac_annotation_names_its_genes_and_no_transcript() -> None:
    wire = StrainWire.model_validate_json(
        (FIXTURES / "strain_pcynM_pkac.json").read_text()
    )

    genes = annotated_genes(wire.annotation)

    assert sorted(genes) == [
        f"PcyM_07{n}"
        for n in [
            "35600",
            "35700",
            "35800",
            "35900",
            "36000",
            "36050",
            "36100",
            "36200",
            "36400",
            "36500",
            "36600",
            "36700",
            "36800",
            "37000",
            "37100",
            "37200",
            "37300",
            "37400",
        ]
    ]
    assert len(wire.annotation) == 104

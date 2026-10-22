import pytest
from scripts.record_audit_strain import StrainWire
from tests._support.audit_site import Genome, members
from tests._support.audit_wire import (
    FIXTURES,
    ServedRecords,
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


class Strain:
    def __init__(
        self, monkeypatch: pytest.MonkeyPatch, name: str, abbrev: str, seqid: str
    ) -> None:
        self.wire = StrainWire.model_validate_json((FIXTURES / name).read_text())
        self.records: ServedRecords = install_records(monkeypatch, self.wire)
        self.genome: Genome = install_genome(monkeypatch, self.wire, abbrev, seqid)
        self.rows: RowReads = serve_recorded_rows(
            monkeypatch,
            [*self.wire.gene_answers, *self.wire.row_answers],
            self.wire.protein_answers,
        )
        self.reports: ReportSite = serve_private(monkeypatch, [])[1]
        self.annotation: Annotation = install_annotation(
            monkeypatch, self.wire.annotation
        )


async def test_the_recorded_pkac_strain_model_misses_an_exon_its_genome_encodes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    strain = Strain(monkeypatch, "strain_pcynM_pkac.json", "pcynM", "PcyM_07")
    wire, genome, rows, annotation = (
        strain.wire,
        strain.genome,
        strain.rows,
        strain.annotation,
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
    assert strain.reports.datasets == []
    assert rows.protein_reads == ["PcyM_0736700", "PCYB_074210"]
    assert rows.reads == ["PcyM_0736700", "PCYB_074210"]
    assert annotation.lists == ["pcynM"]
    assert annotation.reads == [("PcyM_07", 1375622, 1389462)]
    assert wire.reference == "PCYB_074210"
    assert [m.gene for m in result.models] == ["PcyM_0736700", "PCYB_074210"]
    assert [(m.seqid, m.strand) for m in result.models] == [
        ("PcyM_07", "+"),
        ("DF157099", "+"),
    ]
    assert result.models[0].cds == [
        (1381622, 1381745),
        (1382306, 1382465),
        (1382631, 1382790),
        (1383064, 1383462),
    ]
    assert result.models[1].cds == [
        (1385909, 1386032),
        (1386174, 1386331),
        (1386568, 1386752),
        (1386918, 1387077),
        (1387255, 1387653),
    ]
    assert result.models[1].transcript == "PCYB_074210-t26_1"
    assert strain.records.reads == [
        ["Orthologs"],
        [],
        ["GeneModelDump"],
        ["GeneModelDump"],
    ]
    assert strain.records.genes[-2:] == ["PcyM_0736700", "PCYB_074210"]


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
    strain = Strain(monkeypatch, "strain_pfalDd2_yip1.json", "pfalDd2", "PfDd2_14")
    wire, genome, rows, annotation = (
        strain.wire,
        strain.genome,
        strain.rows,
        strain.annotation,
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
    assert strain.reports.datasets == []
    assert rows.protein_reads == [wire.gene, "PF3D7_1472100"]
    assert [(m.gene, m.seqid, m.strand) for m in result.models] == [
        ("PfDd2_140076300", "PfDd2_14", "-"),
        ("PF3D7_1472100", "Pf3D7_14_v3", "-"),
    ]
    assert result.models[0].cds == [
        (2919589, 2919676),
        (2919916, 2920013),
        (2920127, 2920213),
        (2920307, 2920388),
        (2920518, 2921032),
    ]
    assert result.models[1].cds == [
        (2941600, 2941686),
        (2941830, 2941905),
        (2942146, 2942243),
        (2942354, 2942440),
        (2942532, 2942613),
        (2942745, 2943259),
    ]
    assert result.models[1].exons[0] == (2941398, 2941686)
    assert strain.records.reads[-2:] == [["GeneModelDump"], ["GeneModelDump"]]
    assert strain.records.genes[-2:] == [wire.gene, "PF3D7_1472100"]


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

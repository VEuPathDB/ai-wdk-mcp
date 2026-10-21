import json
from pathlib import Path

from pydantic import JsonValue
from scripts.record_audit_fixtures import (
    MODES,
    LengthWire,
    ProteinTarget,
    Region,
    with_proteins,
    write_lengths,
    write_regions,
    write_served,
)


def test_a_strain_region_is_the_gene_padded_by_three_kilobases() -> None:
    assert [(s.file, s.padded, s.strand) for s in MODES["pseudogene"].strains] == [
        ("pfalNF54_piga.json", (1060699, 1068985), "-"),
        ("pfalDd2_tert.json", (620981, 634535), "+"),
    ]


def test_the_selenocysteine_strain_region_is_the_gene_without_padding() -> None:
    recording = MODES["selenocysteine"]
    assert recording.site == "toxodb"
    assert [(s.file, s.padded, s.strand) for s in recording.strains] == [
        ("tgonGT1_selk.json", (5359280, 5361636), "+"),
    ]


def test_a_recorded_protein_joins_its_region(tmp_path: Path) -> None:
    region = Region(
        seqid="TGGT1_chrXI", start=1, end=6, strand="+", sequence="ATGTGA", cds=[]
    )
    joined = with_proteins(
        {"model.json": region, "reference.json": region, "plain.json": region},
        [
            ProteinTarget(file="model.json", gene="g1"),
            ProteinTarget(file="reference.json", gene="g2", reference=True),
        ],
        {"g1": "MK", "g2": "MU"},
    )
    write_regions(tmp_path, joined)
    read = {name: json.loads((tmp_path / name).read_text()) for name in joined}
    assert read["model.json"]["model_protein"] == "MK"
    assert "reference_protein" not in read["model.json"]
    assert read["reference.json"]["reference_protein"] == "MU"
    assert "model_protein" not in read["plain.json"]


def test_the_context_recording_reads_piga_orthologs_and_its_neighbourhood() -> None:
    recording = MODES["context"]
    assert recording.site == "plasmodb"
    assert [(t.file, t.gene) for t in recording.orthologs] == [
        ("pfal3D7_piga_orthologs.json", "PF3D7_1032400")
    ]
    assert [
        (t.file, t.organism, t.seqid, t.start, t.end) for t in recording.neighbourhoods
    ] == [
        (
            "pfal3D7_piga_neighbours.json",
            "Plasmodium falciparum 3D7",
            "Pf3D7_10_v3",
            1290000,
            1320000,
        )
    ]


def test_recorded_wire_bodies_are_written_as_served(tmp_path: Path) -> None:
    table: list[JsonValue] = [
        {"ortho_gene_source_id": "X", "is_syntenic": "yes", "gene": {"url": "u"}}
    ]
    write_served(tmp_path, {"o.json": table})

    assert json.loads((tmp_path / "o.json").read_text()) == table


def test_the_length_recording_reads_the_cynomolgi_m_pkac() -> None:
    recording = MODES["length"]
    assert recording.site == "plasmodb"
    assert [(t.file, t.gene, t.proteins) for t in recording.lengths] == [
        ("pcynM_pkac_length.json", "PcyM_0736700", ["PCYB_074210"])
    ]


def test_a_length_recording_holds_the_served_bodies(tmp_path: Path) -> None:
    served: dict[str, JsonValue] = {"attributes": {}, "tables": {"Orthologs": []}}
    recorded = LengthWire(
        gene="G",
        records=[served],
        gene_answers=[{"meta": {"totalCount": 1}, "records": []}],
        row_answers=[{"meta": {"totalCount": 0}, "records": []}],
        protein_answers=[],
        contig_length=10,
        window_start=1,
        window="ATGAAATAA",
    )
    write_lengths(tmp_path, {"g.json": recorded})

    written = json.loads((tmp_path / "g.json").read_text())
    assert written["records"] == [served]
    assert written["gene_answers"] == [{"meta": {"totalCount": 1}, "records": []}]
    assert LengthWire.model_validate_json((tmp_path / "g.json").read_text()) == recorded

import json

from scripts.record_audit_fixtures import (
    MODES,
    ProteinTarget,
    Region,
    with_proteins,
    write_regions,
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


def test_a_recorded_protein_joins_its_region(tmp_path) -> None:
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

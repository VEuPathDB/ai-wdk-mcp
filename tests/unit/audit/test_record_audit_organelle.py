from pathlib import Path

from scripts.record_audit_organelle import (
    CONTIGS,
    GENE_FILE,
    REFERENCE,
    SITE,
    ContigRecording,
    GeneRecording,
    trim_statement,
    write_recordings,
)


def test_the_recording_reads_five_falciparum_mitochondrial_contigs() -> None:
    assert SITE == "plasmodb"
    assert [(t.file, t.organism, t.seqid) for t in CONTIGS] == [
        (
            "organelle_pfal3D7_mito.json",
            "Plasmodium falciparum 3D7",
            "Pf3D7_MIT_v3",
        ),
        (
            "organelle_pfalNF54_mito.json",
            "Plasmodium falciparum NF54",
            "CM019798.1",
        ),
        ("organelle_pfalSN01_mito.json", "Plasmodium falciparum SN01", "PfSN01_MT"),
        ("organelle_pfal7G8_mito.json", "Plasmodium falciparum 7G8", "Pf7G8_MT"),
        (
            "organelle_pfal7G82019_mito.json",
            "Plasmodium falciparum 7G8 2019",
            "CM019769.1",
        ),
    ]


def test_the_reference_is_the_3d7_cytochrome_b() -> None:
    assert (REFERENCE, GENE_FILE) == ("PF3D7_MIT02300", "organelle_pfal3D7_cytb.json")


def test_recordings_read_back(tmp_path: Path) -> None:
    contig = ContigRecording(
        organism="Plasmodium falciparum 3D7",
        abbrev="pfal3D7",
        seqid="MT",
        length=6,
        sequence="ATGTAA",
        served_meta={"totalCount": 5, "responseCount": 5},
        genes=[{"id": [], "attributes": {}}],
        trim=trim_statement("MT"),
        record={"id": [], "attributes": {}, "tables": {}},
    )
    gene = GeneRecording(
        gene="G",
        report={"meta": {"totalCount": 0}, "records": []},
        record={"id": [], "attributes": {}, "tables": {}},
    )
    write_recordings(tmp_path, {"c.json": contig, "g.json": gene})

    assert (
        ContigRecording.model_validate_json((tmp_path / "c.json").read_text()) == contig
    )
    assert GeneRecording.model_validate_json((tmp_path / "g.json").read_text()) == gene


def test_the_trim_is_stated_in_the_recording() -> None:
    assert trim_statement("CM019798.1") == (
        "genes holds the served GenesByTaxon records whose sequence_id is "
        "CM019798.1; served_meta is the meta of the whole served answer"
    )

import json
from pathlib import Path

from scripts.record_audit_fixtures import write_lengths
from scripts.record_audit_strain import (
    INTRONS_PKAC,
    MODEL_BUDGET,
    PAIRS,
    SITE,
    StrainWire,
    agrees_with_introns,
    model_rows,
)
from tests._support.audit_wire import FIXTURES


def test_the_strain_recording_reads_pkac_and_the_dd2_yip1_on_plasmodb() -> None:
    assert SITE == "plasmodb"
    assert [(p.file, p.reference) for p in PAIRS] == [
        ("strain_pcynM_pkac.json", "PCYB_074210"),
        ("strain_pfalDd2_yip1.json", "PF3D7_1472100"),
    ]


def test_a_strain_recording_holds_the_reference_beside_the_served_bodies(
    tmp_path: Path,
) -> None:
    recorded = StrainWire(
        gene="S",
        reference="R",
        records=[{"attributes": {}, "tables": {"Orthologs": []}}],
        gene_answers=[{"meta": {"totalCount": 2}, "records": []}],
        row_answers=[],
        protein_answers=[],
        contig_length=10,
        window_start=1,
        window="ATGAAATAA",
        annotation=["S_contig\tVEuPathDB\tprotein_coding_gene\t1\t9\t.\t+\t.\tID=S"],
    )

    write_lengths(tmp_path, {"strain_s.json": recorded})

    written = (tmp_path / "strain_s.json").read_text()
    assert json.loads(written)["reference"] == "R"
    assert StrainWire.model_validate_json(written) == recorded


def served_record(gene: str, tables: dict[str, object]) -> dict[str, object]:
    return {"id": [{"name": "source_id", "value": gene}], "tables": tables}


def test_the_model_rows_are_the_model_table_of_the_named_gene() -> None:
    rows = [{"type": "CDS", "gm_start": "1", "gm_end": "9"}]
    records = [
        served_record("R", {"Orthologs": []}),
        served_record("S", {"GeneModelDump": rows}),
    ]

    assert model_rows(records, "S") == rows
    assert model_rows(records, "R") is None
    assert MODEL_BUDGET == 2


def test_the_recorded_pkac_strain_model_is_the_intron_wires_model() -> None:
    strain = StrainWire.model_validate_json(
        (FIXTURES / "strain_pcynM_pkac.json").read_text()
    )
    introns = (FIXTURES / INTRONS_PKAC).read_text()

    assert agrees_with_introns(strain, introns)
    assert not agrees_with_introns(
        strain.model_copy(update={"gene": strain.reference}), introns
    )

import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from scripts.record_audit_fixtures import write_lengths
from scripts.record_audit_strain import PAIRS, SITE, StrainPair, StrainWire

from veupathdb_mcp.audit.genes import OrthologRow

DD2 = "Plasmodium falciparum Dd2"


def ortholog(gene: str, organism: str) -> OrthologRow:
    return OrthologRow.model_validate(
        {"ortho_gene_source_id": gene, "organism": organism, "is_syntenic": "yes"}
    )


def test_the_strain_recording_reads_pkac_and_the_dd2_yip1_on_plasmodb() -> None:
    assert SITE == "plasmodb"
    assert [(p.file, p.reference, p.strain, p.organism) for p in PAIRS] == [
        ("strain_pcynM_pkac.json", "PCYB_074210", "PcyM_0736700", None),
        ("strain_pfalDd2_yip1.json", "PF3D7_1472100", None, DD2),
    ]


def test_a_named_strain_gene_is_read_as_named() -> None:
    assert PAIRS[0].strain_in([]) == "PcyM_0736700"


def test_the_strain_gene_is_the_one_ortholog_of_its_organism() -> None:
    table = [
        ortholog("PF3D7_1472100", "Plasmodium falciparum 3D7"),
        ortholog("PfDd2_140076300", DD2),
        ortholog("PfHB3_140075800", "Plasmodium falciparum HB3"),
    ]

    assert PAIRS[1].strain_in(table) == "PfDd2_140076300"


@pytest.mark.parametrize("count", [0, 2])
def test_an_organism_without_exactly_one_ortholog_is_refused(count: int) -> None:
    table = [ortholog(f"PfDd2_{k}", DD2) for k in range(count)]

    with pytest.raises(ValueError, match=f"name {count} genes of {DD2}"):
        PAIRS[1].strain_in(table)


@pytest.mark.parametrize(("strain", "organism"), [(None, None), ("PfDd2_1", DD2)])
def test_a_pair_names_its_strain_gene_or_its_organism(
    strain: str | None, organism: str | None
) -> None:
    with pytest.raises(ValidationError, match="names its strain gene or the organism"):
        StrainPair(file="f.json", reference="R", strain=strain, organism=organism)


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
    )

    write_lengths(tmp_path, {"strain_s.json": recorded})

    written = (tmp_path / "strain_s.json").read_text()
    assert json.loads(written)["reference"] == "R"
    assert StrainWire.model_validate_json(written) == recorded

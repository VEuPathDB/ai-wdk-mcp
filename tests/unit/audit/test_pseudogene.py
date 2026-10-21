import random
from pathlib import Path

import pytest
from pydantic import ValidationError
from scripts.record_audit_fixtures import Region

from veupathdb_mcp.audit.codes import GeneticCode, reverse_complement
from veupathdb_mcp.audit.pseudogene import (
    CdsPart,
    ReferenceGene,
    check_pseudogene_call,
)

FIXTURES = Path(__file__).parent / "fixtures"
SENSE = [
    a + b + c
    for a in "ACGT"
    for b in "ACGT"
    for c in "ACGT"
    if a + b + c not in {"TAA", "TAG", "TGA"}
]


def sense_codons(rng: random.Random, count: int) -> str:
    return "".join(rng.choice(SENSE) for _ in range(count))


def two_exon_gene() -> tuple[ReferenceGene, int]:
    rng = random.Random(7)
    exon1 = "ATG" + sense_codons(rng, 29)
    intron = "GT" + "".join(rng.choice("ACGT") for _ in range(116)) + "AG"
    exon2 = sense_codons(rng, 30) + "TAA"
    dna = exon1 + intron + exon2
    second = len(exon1) + len(intron) + 1
    reference = ReferenceGene(
        dna=dna,
        cds=[CdsPart(start=1, end=len(exon1)), CdsPart(start=second, end=len(dna))],
        start=1,
        end=len(dna),
        strand="+",
    )
    return reference, len(exon1)


def region(name: str) -> Region:
    return Region.model_validate_json((FIXTURES / name).read_text())


def coding(strain: Region) -> str:
    sequence = strain.sequence
    return sequence if strain.strand == "+" else reverse_complement(sequence)


def run(reference_name: str, strain_name: str):
    ref = region(reference_name)
    strain = region(strain_name)
    reference = ReferenceGene(
        dna=ref.sequence,
        cds=[CdsPart(start=a, end=b) for a, b in ref.cds],
        start=ref.start,
        end=ref.end,
        strand=ref.strand,
    )
    return check_pseudogene_call(reference, coding(strain), GeneticCode.STANDARD)


def whole(dna: str, strand: str) -> ReferenceGene:
    return ReferenceGene.model_validate(
        {
            "dna": dna,
            "cds": [CdsPart(start=1, end=len(dna))],
            "start": 1,
            "end": len(dna),
            "strand": strand,
        }
    )


def test_the_nf54_piga_pseudogene_call_is_on_an_intact_gene() -> None:
    result = run("pfal3D7_piga.json", "pfalNF54_piga.json")
    assert result.verdict == "INTACT"
    assert result.strain_cds_length == result.reference_cds_length == 1386
    assert result.residue_differences == 0


def test_the_dd2_tert_frameshift_is_not_called_intact() -> None:
    assert run("pfal3D7_tert.json", "pfalDd2_tert.json").verdict == "FRAMESHIFT"


def test_a_minus_strand_pair_is_compared_in_coding_orientation() -> None:
    coding_dna = "ATG" + "GCT" * 30 + "TAA"
    reference = whole(reverse_complement(coding_dna), "-")
    result = check_pseudogene_call(
        reference, "CC" + coding_dna + "GG", GeneticCode.STANDARD
    )
    assert result.verdict == "INTACT"


def test_a_premature_stop_is_a_real_nonsense_allele() -> None:
    coding_dna = "ATG" + "GCT" * 30 + "TAA"
    broken = "ATG" + "GCT" * 10 + "TAA" + "GCT" * 19 + "TAA"
    result = check_pseudogene_call(whole(coding_dna, "+"), broken, GeneticCode.STANDARD)
    assert result.verdict == "PREMATURE_STOP"
    assert result.premature_stops == [12]


def test_a_lost_stop_codon_is_not_called_intact() -> None:
    coding_dna = "ATG" + "GCT" * 30 + "TAA"
    result = check_pseudogene_call(
        whole(coding_dna, "+"), coding_dna[:-3] + "TAC", GeneticCode.STANDARD
    )
    assert result.verdict == "START_OR_STOP_LOST"
    assert result.residue_differences == 1


def test_a_strain_region_without_the_gene_is_not_aligned() -> None:
    coding_dna = "ATG" + "GCT" * 30 + "TAA"
    result = check_pseudogene_call(
        whole(coding_dna, "+"), "GGGGG" * 20, GeneticCode.STANDARD
    )
    assert result.verdict == "NOT_ALIGNED"


def test_an_insert_inside_an_exon_is_a_frameshift() -> None:
    reference, _ = two_exon_gene()
    strain = reference.dna[:40] + "CA" + reference.dna[40:]
    result = check_pseudogene_call(
        reference, "TTTT" + strain + "GGGG", GeneticCode.STANDARD
    )
    assert result.verdict == "FRAMESHIFT"
    assert result.strain_cds_length == result.reference_cds_length + 2


def test_an_indel_deep_in_an_intron_leaves_the_coding_sequence_intact() -> None:
    reference, exon1 = two_exon_gene()
    k = exon1 + 60
    dna = reference.dna
    strain = dna[:k] + "CC" + dna[k : k + 20] + dna[k + 21 :]
    result = check_pseudogene_call(
        reference, "TTTT" + strain + "GGGG", GeneticCode.STANDARD
    )
    assert result.verdict == "INTACT"
    assert result.strain_cds_length == result.reference_cds_length == 183


def test_an_in_frame_codon_deletion_is_one_residue_difference() -> None:
    gene = "ATG" + sense_codons(random.Random(11), 99) + "TAA"
    strain = gene[:150] + gene[153:]
    result = check_pseudogene_call(whole(gene, "+"), strain, GeneticCode.STANDARD)
    assert result.verdict == "INTACT"
    assert result.residue_differences == 1


def test_a_cds_part_that_ends_before_it_starts_is_refused() -> None:
    with pytest.raises(ValidationError, match="ends before it starts"):
        CdsPart(start=20, end=10)


def test_a_reference_whose_dna_does_not_span_its_coordinates_is_refused() -> None:
    with pytest.raises(ValidationError, match="holds 9 bases for a 10 base region"):
        ReferenceGene(
            dna="ATGGCTTAA", cds=[CdsPart(start=1, end=9)], start=1, end=10, strand="+"
        )

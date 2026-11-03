from veupathdb_mcp.audit.variant_calls import (
    MIN_UNCALLED_HOMOPOLYMER,
    ReadCalls,
    VariantAnswer,
    VariantCalls,
    VariantRecord,
    VariantRow,
    judge_calls,
    strain_sample,
)

SNV = "Variant_Pf3D7_01_v3_149598"
INDEL = "Variant_Pf3D7_09_v3_1371054"


def row(strain: str, genotype: str, allele: str | None) -> VariantRow:
    return VariantRow(
        strain=strain,
        genotype=genotype,
        allele=allele,
        depth="57",
        read_frequency="100.00",
    )


def called(answer: VariantAnswer, bases: int | None) -> VariantCalls:
    return VariantCalls(
        site="plasmodb",
        organism="Plasmodium falciparum 3D7",
        seqid="Pf3D7_01_v3",
        start=149597,
        end=149599,
        variants=[SNV],
        sample="DD2_WTSI",
        calls=[],
        answer=answer,
        homopolymer_bases=bases,
    )


def test_the_samples_named_by_the_served_table_match_their_genomes() -> None:
    strains = {"3D7_WTSI", "DD2_WTSI", "HB3_WTSI", "IT_WTSI", "KE01", "7G8_WTSI"}

    assert strain_sample("pfal3D7", strains) == "3D7_WTSI"
    assert strain_sample("pfalDd2", strains) == "DD2_WTSI"
    assert strain_sample("pfalIT", strains) == "IT_WTSI"
    assert strain_sample("pfalKE01", strains) == "KE01"
    assert strain_sample("pfal7G8-2019", strains) is None
    assert strain_sample("pfalNF54", strains) is None


def test_no_variant_in_any_sample() -> None:
    assert judge_calls("pfalDd2", []) == ReadCalls(
        answer="NO_VARIANT_CALLED", sample=None, calls=[]
    )


def test_a_strain_outside_the_sequenced_samples_is_not_sampled() -> None:
    records = [
        VariantRecord(
            variant=SNV,
            reference_allele=None,
            rows=[row("DD2_WTSI", "0", "G")],
        )
    ]

    assert judge_calls("pfalNF54", records) == ReadCalls(
        answer="NOT_SAMPLED", sample=None, calls=[]
    )


def test_an_alternate_allele_of_another_length_is_an_indel_in_the_strain() -> None:
    records = [
        VariantRecord(
            variant=INDEL,
            reference_allele="ATCTTCATCTTCATCT",
            rows=[row("KE01", "1", "T"), row("KH01", "0", "ATCTTCATCTTCATCT")],
        )
    ]

    read = judge_calls("pfalKE01", records)

    assert (read.answer, read.sample) == ("INDEL_CALLED", "KE01")
    assert [
        (c.variant, c.genotype, c.allele, c.depth, c.read_frequency) for c in read.calls
    ] == [(INDEL, "1", "T", "57", "100.00")]


def test_the_reference_allele_of_an_indel_site_is_no_indel_in_the_strain() -> None:
    records = [
        VariantRecord(
            variant=INDEL,
            reference_allele="T",
            rows=[row("KE01", "0", "ATCTTCT")],
        )
    ]

    assert judge_calls("pfalKE01", records).answer == "NO_INDEL_CALLED"


def test_a_snv_is_no_indel_in_the_strain() -> None:
    records = [
        VariantRecord(
            variant=SNV, reference_allele=None, rows=[row("DD2_WTSI", "1", "A")]
        )
    ]

    assert judge_calls("pfalDd2", records).answer == "NO_INDEL_CALLED"


def test_a_heterozygous_allele_of_another_length_is_an_indel() -> None:
    records = [
        VariantRecord(
            variant=INDEL, reference_allele="A", rows=[row("KE01", "0/1", "A/AT")]
        )
    ]

    assert judge_calls("pfalKE01", records).answer == "INDEL_CALLED"


def test_reads_with_no_coverage_are_not_covered() -> None:
    records = [
        VariantRecord(
            variant=SNV, reference_allele=None, rows=[row("KE01", "No call", None)]
        )
    ]

    assert judge_calls("pfalKE01", records).answer == "NOT_COVERED"


def test_an_uncalled_homopolymer_cannot_be_determined_from_served_data() -> None:
    assert not called("NO_VARIANT_CALLED", MIN_UNCALLED_HOMOPOLYMER).determinable
    assert not called("NO_INDEL_CALLED", 28).determinable


def test_an_uncalled_short_run_or_a_repeat_can_be_determined() -> None:
    assert called("NO_VARIANT_CALLED", MIN_UNCALLED_HOMOPOLYMER - 1).determinable
    assert called("NO_INDEL_CALLED", None).determinable


def test_a_called_indel_is_determined_whatever_the_run() -> None:
    assert called("INDEL_CALLED", 28).determinable


def test_a_strain_with_no_reads_is_not_determined() -> None:
    assert not called("NOT_SAMPLED", None).determinable
    assert not called("NOT_COVERED", None).determinable

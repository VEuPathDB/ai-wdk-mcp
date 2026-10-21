from veupathdb_mcp.audit.codes import (
    GeneticCode,
    infer_code,
    reverse_complement,
    six_frames,
    translate,
)


def test_the_standard_code_reads_tga_as_stop() -> None:
    assert translate("ATGTGAGGT") == "M*G"


def test_the_ctg_clade_reads_ctg_as_serine() -> None:
    assert translate("CTGCTG", GeneticCode.CTG_SERINE) == "SS"
    assert translate("CTGCTG") == "LL"


def test_the_organelle_code_reads_tga_as_tryptophan() -> None:
    assert translate("TGA", GeneticCode.UGA_TRYPTOPHAN) == "W"


def test_an_ambiguous_codon_is_x() -> None:
    assert translate("ANG") == "X"


def test_six_frames_cover_both_strands() -> None:
    frames = six_frames("ATGAAACCCTAG")
    assert [(f.strand, f.offset) for f in frames] == [
        ("+", 0),
        ("+", 1),
        ("+", 2),
        ("-", 0),
        ("-", 1),
        ("-", 2),
    ]
    assert frames[0].protein == "MKP*"
    assert frames[3].protein == translate(reverse_complement("ATGAAACCCTAG"))
    assert frames[3].protein == "LGFH"


def test_offset_frames_on_both_strands() -> None:
    frames = six_frames("ATGAAACCCTAG")
    assert frames[1].protein == "*NP"
    assert frames[4].protein == "*GF"


def test_reverse_complement_maps_the_iupac_alphabet_in_both_cases() -> None:
    assert reverse_complement("atgR") == "Ycat"
    assert reverse_complement("ACGTN") == "NACGT"
    assert reverse_complement("ACGTRYKMSWBDHVN") == "NBDHVWSKMRYACGT"
    assert reverse_complement("acgtrykmswbdhvn") == "nbdhvwskmryacgt"


def test_ncbi_table_3_reads_tga_as_w_ata_as_m_and_ctn_as_t() -> None:
    assert (
        translate("TGAATACTTCTCCTACTGAGAAGG", GeneticCode.YEAST_MITOCHONDRIAL)
        == "WMTTTTRR"
    )


def test_ncbi_table_5_reads_tga_as_w_ata_as_m_and_agr_as_s() -> None:
    assert (
        translate("TGAATACTTCTCCTACTGAGAAGG", GeneticCode.INVERTEBRATE_MITOCHONDRIAL)
        == "WMLLLLSS"
    )


def test_a_standard_gene_infers_the_standard_code() -> None:
    assert infer_code("ATGCTGTGGTAA", "MLW") is GeneticCode.STANDARD


def test_a_candida_gene_infers_ctg_as_serine() -> None:
    assert infer_code("ATGCTGAAATAA", "MSK") is GeneticCode.CTG_SERINE


def test_an_organelle_gene_infers_tga_as_tryptophan() -> None:
    assert infer_code("ATGTGAAAATAA", "MWK") is GeneticCode.UGA_TRYPTOPHAN


def test_a_yeast_mitochondrial_gene_infers_ncbi_table_3() -> None:
    assert infer_code("ATGATACTTTGATAA", "MMTW") is GeneticCode.YEAST_MITOCHONDRIAL


def test_an_invertebrate_mitochondrial_gene_infers_ncbi_table_5() -> None:
    assert (
        infer_code("ATGATAAGAAGGTGATAA", "MMSSW")
        is GeneticCode.INVERTEBRATE_MITOCHONDRIAL
    )


def test_ncbi_table_3_comes_before_table_5_when_both_explain_the_protein() -> None:
    assert infer_code("ATGATATGATAA", "MMW") is GeneticCode.YEAST_MITOCHONDRIAL


def test_the_first_code_in_order_wins_when_every_code_explains_the_protein() -> None:
    assert infer_code("ATGAAATAA", "MK") is GeneticCode.STANDARD


def test_a_selenoprotein_reads_its_sec_under_the_standard_code() -> None:
    assert infer_code("ATGAAATGAGGTTAA", "MKUG") is GeneticCode.STANDARD


def test_a_sec_is_read_under_the_ctg_code_where_tga_is_a_stop() -> None:
    assert infer_code("ATGCTGTGATAA", "MSU") is GeneticCode.CTG_SERINE


def test_a_sec_is_not_explained_under_a_code_that_reads_tga_as_tryptophan() -> None:
    assert infer_code("ATGTGATGATAA", "MWU") is None


def test_a_sec_facing_a_stop_other_than_tga_is_not_explained() -> None:
    assert infer_code("ATGAAATAGGGTTAA", "MKUG") is None


def test_an_alternative_start_codon_is_read_as_methionine() -> None:
    assert infer_code("TTGAAATAA", "MK") is GeneticCode.STANDARD


def test_any_first_codon_is_read_as_methionine() -> None:
    assert infer_code("GCCAAATAA", "MK") is GeneticCode.STANDARD


def test_a_cds_without_its_stop_codon_still_infers_a_code() -> None:
    assert infer_code("ATGAAA", "MK") is GeneticCode.STANDARD


def test_only_the_trailing_stop_codon_is_dropped() -> None:
    assert infer_code("ATGTAAAAATAA", "MK") is None
    assert infer_code("ATGAAATAATAA", "MK") is None


def test_a_cds_whose_length_is_not_a_multiple_of_three_infers_no_code() -> None:
    assert infer_code("ATGAAATA", "MK") is None
    assert infer_code("ATGAAATAAT", "MK") is None


def test_an_empty_cds_infers_no_code() -> None:
    assert infer_code("", "") is None


def test_no_code_explains_a_mismatch() -> None:
    assert infer_code("ATGAAATAA", "MW") is None

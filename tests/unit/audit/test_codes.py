from veupathdb_mcp.audit.codes import (
    GeneticCode,
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

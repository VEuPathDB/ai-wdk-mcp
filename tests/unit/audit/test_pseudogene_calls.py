import pytest
from pydantic import ValidationError

from veupathdb_mcp.audit.genes import GeneRow
from veupathdb_mcp.audit.pseudogene_calls import (
    FAMILY_WORDS,
    GenomePseudogeneCalls,
    PseudogeneCall,
    UnpairedCounts,
    UnpairedPseudogene,
    pseudogene_calls_of,
)

STRAIN = "Plasmodium falciparum NF54"
REFERENCE = "Plasmodium falciparum 3D7"
NO_GROUP = "N/A (orthology not determined for pseudogenes)"
NC_GROUP = "N/A (orthology not determined for transcripts that are not protein-coding)"
KINASE = "serine/threonine protein kinase, putative"


def gene(
    name: str,
    *,
    product: str = KINASE,
    group: str = "OG8_0000001",
    pseudo: bool | None = False,
    organism: str = REFERENCE,
) -> GeneRow:
    return GeneRow(
        gene=name,
        organism=organism,
        ortholog_group=group,
        protein_length=None if pseudo else 300,
        name="",
        product=product,
        sequence_id="chr1",
        start=1,
        end=900,
        strand="+",
        pseudo=pseudo,
        gene_type="pseudogene" if pseudo else "protein coding gene",
    )


def pseudogene(name: str, product: str = KINASE, group: str = NO_GROUP) -> GeneRow:
    return gene(name, product=product, group=group, pseudo=True, organism=STRAIN)


def calls(genome: list[GeneRow], reference: list[GeneRow]) -> list[PseudogeneCall]:
    return pseudogene_calls_of(STRAIN, REFERENCE, genome, reference).calls


def pairs(genome: list[GeneRow], reference: list[GeneRow]) -> list[tuple[str, str]]:
    return [(c.pseudogene, c.reference_gene) for c in calls(genome, reference)]


def test_a_group_with_one_coding_reference_gene_pairs_by_group() -> None:
    found = calls(
        [pseudogene("P1", product="kinase fragment", group="OG8_0000010")],
        [gene("R1", group="OG8_0000010"), gene("R2", group="OG8_0000011")],
    )

    assert found == [
        PseudogeneCall(
            pseudogene="P1",
            reference_gene="R1",
            product="kinase fragment",
            basis="ORTHOLOG_GROUP",
        )
    ]


def test_a_group_with_two_reference_genes_does_not_pair() -> None:
    reference = [
        gene("R1", group="OG8_0000010", product="kinase A"),
        gene("R2", group="OG8_0000010", product="kinase B"),
    ]

    assert pairs([pseudogene("P1", "kinase A", "OG8_0000010")], reference) == []


def test_a_pseudogene_without_a_group_pairs_by_identical_product() -> None:
    found = calls(
        [pseudogene("P1")],
        [gene("R1", group="OG8_0000010"), gene("R2", product="other")],
    )

    assert [(c.reference_gene, c.product, c.basis) for c in found] == [
        ("R1", KINASE, "PRODUCT")
    ]


def test_a_product_two_coding_reference_genes_hold_does_not_pair() -> None:
    reference = [gene("R1", group="OG8_0000010"), gene("R2", group="OG8_0000011")]

    assert pairs([pseudogene("P1")], reference) == []


def test_a_product_pairs_only_when_it_is_identical() -> None:
    reference = [gene("R1", group="OG8_0000010", product="Serine/threonine kinase")]

    assert pairs([pseudogene("P1", "serine/threonine kinase")], reference) == []


def test_a_residual_group_is_no_group() -> None:
    found = calls(
        [pseudogene("P1", group="OGR8_0000001")],
        [gene("R1", group="OG8_0000010")],
    )

    assert [(c.reference_gene, c.basis) for c in found] == [("R1", "PRODUCT")]


def test_reference_pseudogenes_and_genes_without_a_group_are_not_coding() -> None:
    reference = [
        gene("R1", group="OG8_0000010"),
        gene("R2", group=NO_GROUP, pseudo=True),
        gene("R3", group=NC_GROUP),
    ]

    assert pairs([pseudogene("P1")], reference) == [("P1", "R1")]
    assert pairs([pseudogene("P1")], reference[1:]) == []


def test_a_reference_gene_in_a_residual_group_is_not_coding() -> None:
    reference = [gene("R1", group="OGR8_0000010")]

    assert pairs([pseudogene("P1")], reference) == []


def test_a_flagged_reference_gene_that_codes_no_protein_is_not_coding() -> None:
    reference = [
        gene("R1", group="OG8_0000010").model_copy(update={"gene_type": "ncRNA gene"})
    ]

    assert pairs([pseudogene("P1")], reference) == []


@pytest.mark.parametrize(
    "product",
    [
        "erythrocyte membrane protein 1, PfEMP1",
        "rifin",
        "stevor",
        "conserved Plasmodium protein, unknown function",
        "hypothetical protein",
        "Plasmodium exported protein (PHISTb), unknown function",
        "DnaJ protein, putative",
        "merozoite surface protein MSP7",
        "histone H3 variant",
        "ATP-dependent RNA helicase, variant",
    ],
)
def test_a_product_holding_a_listed_word_does_not_pair(product: str) -> None:
    reference = [gene("R1", group="OG8_0000010", product=product)]

    assert pairs([pseudogene("P1", product)], reference) == []
    assert pairs([pseudogene("P2", product, "OG8_0000010")], reference) == []


def test_a_group_pair_is_left_out_when_the_reference_product_holds_a_word() -> None:
    reference = [gene("R1", group="OG8_0000010", product="rifin")]

    assert pairs([pseudogene("P1", "fragment", "OG8_0000010")], reference) == []


def test_the_family_words_are_the_prototype_list() -> None:
    assert FAMILY_WORDS == (
        "erythrocyte membrane protein 1",
        "rifin",
        "stevor",
        "phist",
        "surfin",
        "pfmc-2tm",
        "exported protein",
        "unknown function",
        "hypothetical",
        "plasmodium exported",
        "fikk",
        "acyl-coa synthetase",
        "var",
        "early transcribed membrane",
        "etramp",
        "dnaj",
        "lysophospholipase",
        "gbp",
        "erythrocyte binding",
        "reticulocyte binding",
        "clag",
        "sera",
        "ring-infected",
        "knob",
        "msp",
    )


def test_only_genes_the_site_flags_pseudo_are_calls() -> None:
    genome = [
        pseudogene("P2"),
        gene("C1", organism=STRAIN),
        gene("U1", pseudo=None, organism=STRAIN),
        pseudogene("P1", product="unpaired"),
    ]

    result = pseudogene_calls_of(STRAIN, REFERENCE, genome, [gene("R1")])

    assert (result.genes, result.pseudogenes, result.unflagged) == (4, 2, 1)
    assert [c.pseudogene for c in result.calls] == ["P2"]
    assert (result.organism, result.reference_organism) == (STRAIN, REFERENCE)
    assert result.no_gene_flagged is False


def test_unflagged_reference_genes_are_counted_and_do_not_pair() -> None:
    reference = [gene("R1", pseudo=None), gene("R2", product="other"), gene("R3")]

    result = pseudogene_calls_of(STRAIN, REFERENCE, [pseudogene("P1")], reference)

    assert (result.reference_genes, result.reference_unflagged) == (3, 1)
    assert [(c.pseudogene, c.reference_gene) for c in result.calls] == [("P1", "R3")]


def test_a_genome_that_flags_no_gene_says_so() -> None:
    genome = [gene(f"U{i}", pseudo=None, organism=STRAIN) for i in range(3)]

    result = pseudogene_calls_of(STRAIN, REFERENCE, genome, [gene("R1")])

    assert (result.genes, result.pseudogenes, result.unflagged) == (3, 0, 3)
    assert result.calls == []
    assert result.no_gene_flagged is True


def test_a_genome_with_no_pseudogene_is_not_an_unflagged_one() -> None:
    result = pseudogene_calls_of(
        STRAIN, REFERENCE, [gene("C1", organism=STRAIN)], [gene("R1")]
    )

    assert (result.pseudogenes, result.unflagged, result.no_gene_flagged) == (
        0,
        0,
        False,
    )
    assert pseudogene_calls_of(STRAIN, REFERENCE, [], []).no_gene_flagged is False


def test_unpaired_pseudogenes_are_counted_by_reason() -> None:
    reference = [
        gene("R1", group="OG8_0000010"),
        gene("R2", group="OG8_0000011"),
        gene("R3", group="OG8_0000012", product="actin"),
        gene("R4", group="OG8_0000013", product="rifin"),
    ]
    genome = [
        pseudogene("P1"),
        pseudogene("P2", "actin"),
        pseudogene("P3", "tubulin"),
        pseudogene("P4", "rifin"),
        pseudogene("P5", "fragment", "OG8_0000013"),
        pseudogene("P6", "fragment", "OG8_0000099"),
    ]

    result = pseudogene_calls_of(STRAIN, REFERENCE, genome, reference)

    assert [(c.pseudogene, c.reference_gene) for c in result.calls] == [("P2", "R3")]
    assert result.unpaired == UnpairedCounts(
        family_word=2, no_reference=2, several_references=1
    )
    assert result.unpaired_genes == [
        UnpairedPseudogene(pseudogene="P1", reason="SEVERAL_REFERENCES", word=None),
        UnpairedPseudogene(pseudogene="P3", reason="NO_REFERENCE", word=None),
        UnpairedPseudogene(pseudogene="P4", reason="FAMILY_WORD", word="rifin"),
        UnpairedPseudogene(pseudogene="P5", reason="FAMILY_WORD", word="rifin"),
        UnpairedPseudogene(pseudogene="P6", reason="NO_REFERENCE", word=None),
    ]


@pytest.mark.parametrize(
    ("reason", "word"),
    [("FAMILY_WORD", None), ("NO_REFERENCE", "rifin")],
)
def test_an_unpaired_pseudogene_names_a_word_only_for_a_family_word(
    reason: str, word: str | None
) -> None:
    with pytest.raises(ValidationError, match="names its listed word"):
        UnpairedPseudogene.model_validate(
            {"pseudogene": "P1", "reason": reason, "word": word}
        )


def test_calls_are_ordered_by_pseudogene() -> None:
    reference = [gene("R1"), gene("R2", product="other kinase")]
    genome = [pseudogene("P9"), pseudogene("P1", "other kinase"), pseudogene("P5")]

    assert pairs(genome, reference) == [("P1", "R2"), ("P5", "R1"), ("P9", "R1")]


def test_the_calls_serve_in_camel_case() -> None:
    served = pseudogene_calls_of(
        STRAIN,
        REFERENCE,
        [pseudogene("P1"), gene("U1", pseudo=None, organism=STRAIN)],
        [gene("R1")],
    ).model_dump(by_alias=True)

    assert served == {
        "organism": STRAIN,
        "referenceOrganism": REFERENCE,
        "genes": 2,
        "pseudogenes": 1,
        "unflagged": 1,
        "referenceGenes": 1,
        "referenceUnflagged": 0,
        "calls": [
            {
                "pseudogene": "P1",
                "referenceGene": "R1",
                "product": KINASE,
                "basis": "PRODUCT",
            }
        ],
        "unpairedGenes": [],
        "noGeneFlagged": False,
        "unpaired": {"familyWord": 0, "noReference": 0, "severalReferences": 0},
    }


def served_calls(pseudogenes: int, calls: int, unpaired: int) -> GenomePseudogeneCalls:
    call = PseudogeneCall(
        pseudogene="P1", reference_gene="R1", product=KINASE, basis="PRODUCT"
    )
    left = UnpairedPseudogene(pseudogene="P2", reason="NO_REFERENCE", word=None)
    return GenomePseudogeneCalls(
        organism=STRAIN,
        reference_organism=REFERENCE,
        genes=5,
        pseudogenes=pseudogenes,
        unflagged=0,
        reference_genes=1,
        reference_unflagged=0,
        calls=[call] * calls,
        unpaired_genes=[left] * unpaired,
    )


def test_calls_and_unpaired_pseudogenes_add_up_to_the_pseudogenes() -> None:
    with pytest.raises(ValidationError, match="2 calls and 0 unpaired"):
        served_calls(1, 2, 0)
    with pytest.raises(ValidationError, match="1 calls and 2 unpaired"):
        served_calls(2, 1, 2)


def test_more_flagged_and_unflagged_genes_than_genes_are_refused() -> None:
    with pytest.raises(
        ValidationError, match="6 pseudogenes and 0 unflagged genes exceed the 5"
    ):
        served_calls(6, 0, 6)

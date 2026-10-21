import pytest
from pydantic import ValidationError
from tests._support.proteins import PROTEIN

from veupathdb_mcp.audit.introns_orthologs import (
    OrthologProtein,
    OrthologSet,
    OrthologSupport,
    closest_orthologs,
    ortholog_support,
)

FULL = PROTEIN[:150]
SHORT = FULL[:50] + FULL[90:]


def ortholog(gene: str, species: str, protein: str) -> OrthologProtein:
    return OrthologProtein(gene=gene, species=species, protein=protein)


def read(*proteins: OrthologProtein, named: int | None = None) -> OrthologSet:
    return OrthologSet(named=named or len(proteins), proteins=list(proteins))


def test_an_ortholog_holding_the_restored_exon_backs_the_correction() -> None:
    orthologs = read(
        ortholog("A1", "Plasmodium vivax", FULL),
        ortholog("B1", "Plasmodium knowlesi", SHORT),
        named=3,
    )

    result = ortholog_support(SHORT, FULL, orthologs)

    assert result == OrthologSupport(
        named=3, read=2, compared=["B1", "A1"], for_corrected=1, for_annotated=0
    )


def test_an_ortholog_holding_residues_the_correction_drops_backs_the_model() -> None:
    result = ortholog_support(
        FULL, SHORT, read(ortholog("A1", "Plasmodium vivax", FULL))
    )

    assert (result.for_corrected, result.for_annotated) == (0, 1)


def test_an_ortholog_that_matches_neither_model_backs_neither() -> None:
    unrelated = ortholog("C1", "Toxoplasma gondii", PROTEIN[::-1])

    result = ortholog_support(SHORT, FULL, read(unrelated))

    assert result == OrthologSupport(
        named=1, read=1, compared=["C1"], for_corrected=0, for_annotated=0
    )


def test_each_species_is_read_through_its_closest_copy() -> None:
    copies = [
        ortholog("far", "Plasmodium vivax", PROTEIN[100:]),
        ortholog("near", "Plasmodium vivax", FULL[:140]),
        ortholog("other", "Plasmodium knowlesi", PROTEIN[60:]),
    ]

    chosen = closest_orthologs(FULL, copies)

    assert [c.gene for c in chosen] == ["near", "other"]


def test_at_most_eight_species_are_compared_most_similar_first() -> None:
    copies = [
        ortholog(f"g{k}", f"Plasmodium species{k}", FULL[: 40 + 10 * k])
        for k in range(10)
    ]

    chosen = closest_orthologs(FULL, copies)

    assert [c.gene for c in chosen] == ["g9", "g8", "g7", "g6", "g5", "g4", "g3", "g2"]


def test_an_ortholog_count_that_was_not_read_states_why_and_no_number() -> None:
    result = OrthologSupport.not_read("no Orthologs table")

    assert (result.named, result.read, result.for_corrected) == (None, None, None)
    with pytest.raises(ValidationError, match="or the reason it has none"):
        OrthologSupport(
            named=3,
            read=2,
            compared=[],
            for_corrected=0,
            for_annotated=0,
            reason="no Orthologs table",
        )

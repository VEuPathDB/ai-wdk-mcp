import pytest
from pydantic import ValidationError

from veupathdb_mcp.audit.fusion import FusionAudit, GeneFusionAudit
from veupathdb_mcp.audit.lengths import LengthClass

MERGED = {
    "extra": [(111, 200)],
    "partner": "N3",
    "closest_neighbour": None,
    "neighbour_windows": 7,
    "neighbours": ["N1", "N2", "N3"],
    "product": "methionine aminopeptidase",
    "partner_group": "OG7_0000777",
    "partner_product": "tRNA ligase",
    "partner_copies": ["M2"],
}
UNEXPLAINED = MERGED | {
    "partner": None,
    "closest_neighbour": "N2",
    "neighbour_windows": 2,
    "partner_group": None,
    "partner_product": None,
    "partner_copies": None,
}
SCREEN = {
    "gene_ids": [{"given": "M", "resolved": "M"}],
    "genes": ["M"],
    "ratio": 1.667,
    "group_median": 120,
    "group_copies": 1,
    "group_spread": 0.0,
    "organisms": 10,
    "reference_gene": "R",
}


def test_a_matched_neighbour_answers_camel_case_with_its_computed_counts() -> None:
    fusion = FusionAudit.model_validate(MERGED)

    assert fusion.model_dump(by_alias=True) == {
        "extra": [(111, 200)],
        "partner": "N3",
        "closestNeighbour": None,
        "neighbourWindows": 7,
        "extraWindows": 8,
        "verdict": "EXTRA_MATCHES_NEIGHBOUR",
        "neighbours": ["N1", "N2", "N3"],
        "product": "methionine aminopeptidase",
        "partnerGroup": "OG7_0000777",
        "partnerProduct": "tRNA ligase",
        "partnerCopies": ["M2"],
    }


def test_an_unexplained_answer_names_only_its_closest_neighbour() -> None:
    fusion = FusionAudit.model_validate(UNEXPLAINED)

    assert (fusion.verdict, fusion.partner, fusion.closest_neighbour) == (
        "EXTRA_UNEXPLAINED",
        None,
        "N2",
    )


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"neighbours": ["N1"]}, "N3 is not one of the genes read beside"),
        ({"partner_group": None}, "states the partner's group and product"),
        ({"partner_product": None}, "states the partner's group and product"),
        ({"partner_copies": None}, "lists the partner's copies beside the gene"),
        (
            {"partner_group": "OGR7r1_1"},
            "lists the partner's copies beside the gene",
        ),
        (
            {"partner": None, "closest_neighbour": "N3", "neighbour_windows": 3},
            "states the partner's group and product",
        ),
    ],
)
def test_a_fusion_that_states_what_it_did_not_read_is_refused(
    change: dict[str, object], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        FusionAudit.model_validate({**MERGED, **change})


@pytest.mark.parametrize(
    ("length_class", "fusion"),
    [("LONG", None), ("TYPICAL", MERGED), ("SHORT", MERGED)],
)
def test_only_a_long_gene_carries_a_fusion_check(
    length_class: LengthClass, fusion: dict[str, object] | None
) -> None:
    with pytest.raises(ValidationError, match="only when its class is LONG"):
        GeneFusionAudit.model_validate(
            {**SCREEN, "length_class": length_class, "fusion": fusion}
        )


def test_a_closest_neighbour_that_was_not_read_is_refused() -> None:
    with pytest.raises(ValidationError, match="N9 is not one of the genes read beside"):
        FusionAudit.model_validate(UNEXPLAINED | {"closest_neighbour": "N9"})

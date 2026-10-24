import pytest
from pydantic import ValidationError
from tests._support.intron_genes import (
    E1,
    E2,
    E3,
    E4,
    I1,
    I2,
    I3,
    SPLICED,
    dna,
    junction,
    structure,
)
from tests._support.proteins import PROTEIN

from veupathdb_mcp.audit.codes import GeneticCode
from veupathdb_mcp.audit.intron_judge import (
    judge_introns,
)
from veupathdb_mcp.audit.introns import (
    NO_EVIDENCE,
    GeneStructure,
    IntronDepth,
    IntronEvidence,
    IntronSupport,
    RnaJunction,
    UnreadIntron,
    UnreadOutcome,
)
from veupathdb_mcp.audit.introns_correction import IntronCorrection, correct_model

STANDARD = GeneticCode.STANDARD
READS = [junction(I1, 100), junction(I2, 120), junction(I3, 300)]
KEY = f"{I2[0]}-{I2[1]}"
RETAINED_PROTEIN = PROTEIN[:60] + "V" + "P" * 18 + "Q" + PROTEIN[60:120]


def corrected(
    gene: GeneStructure,
    reads: list[RnaJunction],
    evidence: IntronEvidence = NO_EVIDENCE,
    outcome: UnreadOutcome | None = None,
) -> IntronCorrection:
    unread = judge_introns(gene, reads, evidence).unread
    assert unread is not None
    assert outcome is None or [u.outcome for u in unread] == [outcome]
    return correct_model(gene, unread, dna(), STANDARD)


def test_a_shifted_intron_is_replaced_by_its_junction() -> None:
    gene = structure([E1, E2, (I2[1] + 25, E3[1]), E4])

    result = corrected(gene, READS, outcome="SHIFTED")

    assert result == IntronCorrection(
        cds=[E1, E2, E3, E4], exons=[E1, E2, E3, E4], protein=SPLICED, frame_kept=True
    )


def test_a_missing_exon_is_restored_from_its_chain() -> None:
    result = corrected(structure([E1, E3, E4]), READS, outcome="MISSING_EXON")

    assert (result.cds, result.protein) == ([E1, E2, E3, E4], SPLICED)


def test_a_replaced_intron_is_cut_where_its_junction_is() -> None:
    gene = structure([E1, (E2[0], E2[1] - 40), E3, E4])

    result = corrected(gene, READS, outcome="REPLACED")

    assert (result.cds, result.protein) == ([E1, E2, E3, E4], SPLICED)


@pytest.mark.parametrize(
    ("evidence", "outcome"),
    [
        (IntronEvidence(motifs={KEY: "AT..AC"}), "NONCANONICAL"),
        (
            IntronEvidence(
                motifs={KEY: "GT..AG"},
                depth={
                    KEY: IntronDepth(
                        intron_median_depth=50.0,
                        exon_median_depth=60.0,
                        covered_share=1.0,
                        track="t",
                    )
                },
            ),
            "RETAINED",
        ),
    ],
)
def test_an_intron_kept_in_the_transcript_is_read_as_exon(
    evidence: IntronEvidence, outcome: UnreadOutcome
) -> None:
    reads = [junction(I1, 100), junction(I3, 300)]

    result = corrected(structure([E1, E2, E3, E4]), reads, evidence, outcome)

    assert result.cds == [E1, (E2[0], E3[1]), E4]
    assert result.exons == [E1, (E2[0], E3[1]), E4]
    assert (result.protein, result.frame_kept) == (RETAINED_PROTEIN, True)


def test_a_model_with_an_unexplained_intron_is_refused() -> None:
    gene = structure([E1, E2, E3, E4])
    unread = judge_introns(gene, [junction(I1, 100), junction(I3, 300)]).unread
    assert unread is not None

    with pytest.raises(ValueError, match="no unread intron is UNEXPLAINED"):
        correct_model(gene, unread, dna(), STANDARD)


LINK = IntronSupport(start=I2[0], end=I2[1], reads=120, tracks=1)
DEPTH = IntronDepth(
    intron_median_depth=50.0, exon_median_depth=60.0, covered_share=1.0, track="t"
)
FITTING: list[tuple[UnreadOutcome, int, int, dict[str, object]]] = [
    ("SHIFTED", 1, 0, {}),
    ("REPLACED", 1, 2, {}),
    ("MISSING_EXON", 2, 1, {}),
    ("NONCANONICAL", 0, 1, {"motif": "AT..AC"}),
    ("RETAINED", 0, 1, {"depth": DEPTH}),
    ("UNEXPLAINED", 0, 1, {}),
]


@pytest.mark.parametrize(("outcome", "links", "wrong", "fields"), FITTING)
def test_each_outcome_carries_its_own_number_of_links(
    outcome: UnreadOutcome, links: int, wrong: int, fields: dict[str, object]
) -> None:
    def built(count: int) -> UnreadIntron:
        return UnreadIntron.model_validate(
            {
                "start": I2[0],
                "end": I2[1],
                "in_cds": True,
                "outcome": outcome,
                "replacement": [LINK] * count,
                **fields,
            }
        )

    assert len(built(links).replacement) == links
    with pytest.raises(ValidationError, match="SHIFTED and REPLACED have one"):
        built(wrong)


@pytest.mark.parametrize(
    ("outcome", "fields"),
    [
        ("NONCANONICAL", {}),
        ("NONCANONICAL", {"motif": "GT..AG"}),
        ("RETAINED", {}),
    ],
)
def test_a_kept_intron_carries_the_evidence_that_kept_it(
    outcome: UnreadOutcome, fields: dict[str, object]
) -> None:
    with pytest.raises(ValidationError, match="carries the evidence"):
        UnreadIntron.model_validate(
            {
                "start": I2[0],
                "end": I2[1],
                "in_cds": True,
                "outcome": outcome,
                "replacement": [],
                **fields,
            }
        )


def test_unread_intron_fields_round_trip() -> None:
    replaced = UnreadIntron(
        start=I2[0],
        end=I2[1],
        in_cds=True,
        outcome="REPLACED",
        replacement=[IntronSupport(start=1341, end=1360, reads=100, tracks=2)],
    )
    noncanonical = UnreadIntron(
        start=I2[0],
        end=I2[1],
        in_cds=True,
        outcome="NONCANONICAL",
        replacement=[],
        motif="AT..AC",
    )
    retained = UnreadIntron(
        start=I2[0],
        end=I2[1],
        in_cds=True,
        outcome="RETAINED",
        replacement=[],
        motif="GT..AG",
        depth=IntronDepth(
            intron_median_depth=12.5,
            exon_median_depth=40.0,
            covered_share=0.95,
            track="t",
        ),
    )

    dumped = [
        u.model_dump(by_alias=True, mode="json")
        for u in (replaced, noncanonical, retained)
    ]

    assert dumped[0]["replacement"] == [
        {"start": 1341, "end": 1360, "reads": 100, "tracks": 2}
    ]
    assert (dumped[0]["motif"], dumped[0]["depth"]) == (None, None)
    assert dumped[1]["motif"] == "AT..AC"
    assert dumped[2]["depth"] == {
        "intronMedianDepth": 12.5,
        "exonMedianDepth": 40.0,
        "coveredShare": 0.95,
        "track": "t",
        "depthShare": 0.312,
    }
    assert [UnreadIntron.model_validate(d) for d in dumped] == [
        replaced,
        noncanonical,
        retained,
    ]

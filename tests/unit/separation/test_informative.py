"""A candidate informs in the direction its controls beat chance, or not at all."""

from veupathdb.domain.strategy import CombineOp

from veupathdb_mcp.controls import NegativeControls, PositiveControls
from veupathdb_mcp.separation import (
    Candidate,
    CandidateSource,
    MeasuredCandidate,
    SeparationResult,
)
from veupathdb_mcp.separation.assemble import assemble, leaf_ids, shortfall

POSITIVES = [f"PF3D7_01{i:05d}" for i in range(80)]
SIGNAL_PEPTIDE_NEGATIVES = [f"PF3D7_02{i:05d}" for i in range(40)]
INVASION_NEGATIVES = [f"PF3D7_03{i:05d}" for i in range(55)]


def _measured(
    candidate_id: str,
    recovered: int,
    negatives: list[str],
    admitted: int,
    size: int,
) -> MeasuredCandidate:
    return MeasuredCandidate(
        candidate=Candidate(
            id=candidate_id,
            search_name=f"GenesBy{candidate_id}",
            display_name=candidate_id,
            parameters={},
            source=CandidateSource.CATALOG,
            basis="the site's catalog",
        ),
        result_size=size,
        positive=PositiveControls.filed(POSITIVES, set(POSITIVES[:recovered])),
        negative=NegativeControls.filed(negatives, set(negatives[:admitted])),
    )


def _read(
    mode: str, recovered: int, negatives: list[str], admitted: int
) -> SeparationResult:
    return SeparationResult.model_validate(
        {
            "site_id": "plasmodb",
            "mode": mode,
            "organisms": ["Plasmodium falciparum 3D7"],
            "positives": POSITIVES,
            "negatives": negatives,
            "unresolved_positive": [],
            "unresolved_negative": [],
            "tree": {"kind": "leaf", "candidate_id": "c1"},
            "positive": PositiveControls.filed(POSITIVES, set(POSITIVES[:recovered])),
            "negative": NegativeControls.filed(negatives, set(negatives[:admitted])),
            "result_size": 5720,
            "predicted_matches_read": True,
            "shortfall": [],
            "measured": [],
            "skipped": [],
            "charged_requests": 0,
            "budget": 250,
        }
    )


def test_signal_peptide_at_52_of_80_and_2_of_40_is_recovering() -> None:
    measured = _measured("SignalP", 52, SIGNAL_PEPTIDE_NEGATIVES, 2, 479)

    assert measured.informs == "recovering"


def test_alphafold_at_80_of_80_and_39_of_40_is_not() -> None:
    measured = _measured("Alphafold", 80, SIGNAL_PEPTIDE_NEGATIVES, 39, 5141)

    assert measured.informs == "neither"


def test_every_gene_at_80_of_80_and_55_of_55_is_not() -> None:
    measured = _measured("GeneModelChars", 80, INVASION_NEGATIVES, 55, 5720)

    assert measured.informs == "neither"


def test_a_whole_genome_candidate_is_measured_and_never_assembled() -> None:
    whole = _measured("Alphafold", 80, SIGNAL_PEPTIDE_NEGATIVES, 39, 5141)
    signal = _measured("SignalP", 52, SIGNAL_PEPTIDE_NEGATIVES, 2, 479)

    assembly = assemble([whole, signal], "exact", POSITIVES)

    assert leaf_ids(assembly.tree) == ["SignalP"]
    assert whole.model_dump(by_alias=True)["informs"] == "neither"


def test_similar_mode_does_not_separate_with_every_gene() -> None:
    assert _read("similar", 80, INVASION_NEGATIVES, 55).separates is False


def test_similar_mode_separates_when_the_read_beats_chance() -> None:
    assert _read("similar", 80, SIGNAL_PEPTIDE_NEGATIVES, 2).separates is True


def test_no_informative_candidate_leaves_no_tree_and_says_so() -> None:
    every_gene = _measured("GeneModelChars", 80, INVASION_NEGATIVES, 55, 5720)

    assembly = assemble([every_gene], "similar", POSITIVES)

    assert assembly.tree is None
    assert shortfall("similar", assembly, None, None, [every_gene]) == [
        "No measured criterion tells the positives from the negatives."
    ]


def test_none_of_80_and_30_of_40_is_excluding() -> None:
    measured = _measured("Nuclear", 0, SIGNAL_PEPTIDE_NEGATIVES, 30, 900)

    assert measured.informs == "excluding"


def test_a_minus_removes_what_an_excluding_candidate_holds() -> None:
    """The cover admits 30 negatives, and the excluding candidate holds those 30."""
    cover = _measured("Secreted", 80, SIGNAL_PEPTIDE_NEGATIVES, 30, 2000)
    nuclear = _measured("Nuclear", 0, SIGNAL_PEPTIDE_NEGATIVES, 30, 900)

    assembly = assemble([cover, nuclear], "exact", POSITIVES)

    assert cover.informs == "recovering"
    assert assembly.tree is not None
    assert (assembly.tree.operator, leaf_ids(assembly.tree)) == (
        CombineOp.MINUS,
        ["Secreted", "Nuclear"],
    )
    assert assembly.recovered == frozenset(POSITIVES)
    assert assembly.admitted == frozenset()


def test_an_excluding_candidate_that_holds_a_recovered_positive_is_not_subtracted() -> (
    None
):
    """One recovered positive beside 30 negatives still excludes, and would drop it."""
    cover = _measured("Secreted", 80, SIGNAL_PEPTIDE_NEGATIVES, 30, 2000)
    leaky = _measured("Leaky", 1, SIGNAL_PEPTIDE_NEGATIVES, 30, 900)

    assembly = assemble([cover, leaky], "exact", POSITIVES)

    assert leaky.informs == "excluding"
    assert leaf_ids(assembly.tree) == ["Secreted"]
    assert len(assembly.admitted) == 30


def test_similar_mode_never_subtracts() -> None:
    cover = _measured("Secreted", 80, SIGNAL_PEPTIDE_NEGATIVES, 30, 2000)
    nuclear = _measured("Nuclear", 0, SIGNAL_PEPTIDE_NEGATIVES, 30, 900)

    assembly = assemble([cover, nuclear], "similar", POSITIVES)

    assert leaf_ids(assembly.tree) == ["Secreted"]

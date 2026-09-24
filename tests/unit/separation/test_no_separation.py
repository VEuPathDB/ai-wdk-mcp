"""When no measured criterion separates the sets, the closest tree and its gaps."""

from tests._support.separation_sets import NEGATIVES, POSITIVES, measured, moves

from veupathdb_mcp.controls import NegativeControls, PositiveControls
from veupathdb_mcp.separation import SeparationResult
from veupathdb_mcp.separation.assemble import assemble, shortfall


def _unseparable() -> list:
    """U holds eight positives and negative 0; V alone recovers 9 and beats no chance."""
    return [
        measured("U", range(8), [0], 300),
        measured("V", [9], [0], 200),
        measured("W", range(5), [1], 400),
    ]


def _result(assembly, positive, negative) -> SeparationResult:
    return SeparationResult(
        site_id="plasmodb",
        mode="exact",
        organisms=["Plasmodium falciparum 3D7"],
        positives=POSITIVES,
        negatives=NEGATIVES,
        unresolved_positive=[],
        unresolved_negative=[],
        tree=assembly.tree,
        positive=positive,
        negative=negative,
        result_size=None,
        predicted_matches_read=True,
        shortfall=[],
        measured=[],
        skipped=[],
        charged_requests=0,
        budget=400,
    )


def _read(assembly) -> tuple[PositiveControls, NegativeControls]:
    return (
        PositiveControls.filed(POSITIVES, assembly.recovered),
        NegativeControls.filed(NEGATIVES, assembly.admitted),
    )


def test_the_closest_tree_is_kept_and_does_not_separate() -> None:
    measured_sets = _unseparable()
    assembly = assemble(measured_sets, "exact", POSITIVES)

    result = _result(assembly, *_read(assembly))

    assert [m.informs for m in measured_sets] == ["recovering", "neither", "neither"]
    assert moves(assembly.tree) == [(None, "U")]
    assert result.separates is False


def test_the_shortfall_names_each_missed_positive_and_admitted_negative() -> None:
    measured_sets = _unseparable()
    assembly = assemble(measured_sets, "exact", POSITIVES)

    sentences = shortfall("exact", assembly, *_read(assembly), measured_sets)

    assert sentences == [
        f"No measured criterion recovers {POSITIVES[8]}.",
        (
            "Only criteria that do not return the positives above chance "
            f"recover {POSITIVES[9]}."
        ),
        (
            f"No measured criterion excludes {NEGATIVES[0]} "
            "without losing a recovered positive."
        ),
    ]


def test_no_positive_recovered_leaves_no_tree_and_says_so() -> None:
    measured_sets = [measured("C", [], [0, 1], 300), measured("F", [], [], 10)]

    assembly = assemble(measured_sets, "exact", POSITIVES)

    assert assembly.tree is None
    assert shortfall("exact", assembly, None, None, measured_sets) == [
        "No measured criterion recovers any positive."
    ]


def test_similar_mode_names_only_the_missed_positives() -> None:
    measured_sets = _unseparable()
    assembly = assemble(measured_sets, "exact", POSITIVES)

    assert shortfall("similar", assembly, *_read(assembly), measured_sets) == [
        f"No measured criterion recovers {POSITIVES[8]}.",
        (
            "Only criteria that do not return the positives above chance "
            f"recover {POSITIVES[9]}."
        ),
    ]


def test_a_similar_read_that_beats_no_chance_is_named() -> None:
    measured_sets = [measured("B", range(10), [6, 7], 900)]
    assembly = assemble(measured_sets, "exact", POSITIVES)
    everything = (
        PositiveControls.filed(POSITIVES, set(POSITIVES)),
        NegativeControls.filed(NEGATIVES, set(NEGATIVES)),
    )

    assert shortfall("similar", assembly, *everything, measured_sets) == [
        "The assembled strategy does not tell the positives from the negatives."
    ]


def test_a_read_that_differs_from_the_prediction_is_named() -> None:
    measured_sets = _unseparable()
    assembly = assemble(measured_sets, "exact", POSITIVES)
    positive = PositiveControls.filed(POSITIVES, assembly.recovered - {POSITIVES[1]})
    negative = NegativeControls.filed(NEGATIVES, assembly.admitted | {NEGATIVES[5]})

    sentences = shortfall("exact", assembly, positive, negative, measured_sets)

    assert (
        f"The site misses {POSITIVES[1]} in the assembled strategy, "
        "although the measured criteria recover it." in sentences
    )
    assert (
        f"The site returns {NEGATIVES[5]} in the assembled strategy, "
        "although the measured criteria exclude it." in sentences
    )

import pytest
from pydantic import ValidationError
from tests._support.missing_site import GT1, gene

from veupathdb_mcp.audit.gene_ids import GeneId
from veupathdb_mcp.audit.genes import GeneRow
from veupathdb_mcp.audit.missing import (
    ANCHOR_MAX_SPAN,
    ANCHOR_REACH,
    MISSING_PAD,
    Anchor,
    Anchors,
    Located,
    MissingGeneAudit,
    find_anchors,
    missing_verdict,
    overlapping,
)
from veupathdb_mcp.audit.served import AUDIT_MAX_WINDOW_BASES

CONTIG = "TGGT1_chrVIIb"


def neighbourhood(before: int, after: int) -> tuple[list[GeneRow], GeneRow]:
    example = gene("EX", 100000, group="OG8_4000000")
    rows = [
        *(
            gene(f"L{k}", 100000 - 2000 * k, group=f"OG8_10{k:05d}")
            for k in range(1, before + 1)
        ),
        example,
        *(
            gene(f"R{k}", 100000 + 2000 * k, group=f"OG8_20{k:05d}")
            for k in range(1, after + 1)
        ),
    ]
    return rows, example


def absent(name: str, group: str, start: int, sequence_id: str = CONTIG) -> GeneRow:
    return gene(name, start, organism=GT1, sequence_id=sequence_id, group=group)


def anchor(neighbour: str, name: str, start: int) -> Anchor:
    return Anchor.model_validate(
        {**absent(name, "OG", start).model_dump(), "neighbour": neighbour}
    )


def picked(anchors: Anchors | None) -> tuple[str, str, str, str] | None:
    if anchors is None:
        return None
    left, right = anchors.left, anchors.right
    return (left.neighbour, left.gene, right.neighbour, right.gene)


def test_anchors_are_the_nearest_neighbours_with_one_copy_in_the_absent_genome() -> (
    None
):
    rows, example = neighbourhood(3, 3)
    genome = [
        absent("G1", "OG8_1000001", 4150000),
        absent("G2", "OG8_1000001", 4900000),
        absent("GL2", "OG8_1000002", 4152000),
        absent("GR2", "OG8_2000002", 4170000),
        absent("GR3", "OG8_2000003", 4172000),
    ]

    anchors = find_anchors(rows, example, genome)

    assert picked(anchors) == ("L2", "GL2", "R2", "GR2")
    assert anchors is not None
    assert anchors.between == (4152899, 4170000)


def test_a_neighbour_with_two_copies_is_not_an_anchor() -> None:
    rows, example = neighbourhood(1, 1)
    genome = [
        absent("G1", "OG8_1000001", 4150000),
        absent("G2", "OG8_1000001", 4160000),
        absent("GR1", "OG8_2000001", 4170000),
    ]

    assert find_anchors(rows, example, genome) is None


def test_the_walk_stops_six_genes_out() -> None:
    rows, example = neighbourhood(ANCHOR_REACH + 1, 1)
    genome = [
        absent("FAR", f"OG8_10{ANCHOR_REACH + 1:05d}", 4150000),
        absent("GR1", "OG8_2000001", 4170000),
    ]

    assert find_anchors(rows, example, genome) is None


def test_a_residual_group_neighbour_is_not_an_anchor() -> None:
    rows, example = neighbourhood(2, 1)
    rows[0] = rows[0].model_copy(update={"ortholog_group": "OGR8r1_1000001"})
    genome = [
        absent("GL1", "OGR8r1_1000001", 4151000),
        absent("GL2", "OG8_1000002", 4150000),
        absent("GR1", "OG8_2000001", 4170000),
    ]

    assert picked(find_anchors(rows, example, genome)) == ("L2", "GL2", "R1", "GR1")


def test_an_orthology_label_that_is_no_group_is_not_an_anchor() -> None:
    rows, example = neighbourhood(2, 1)
    label = "N/A (orthology not determined for pseudogenes)"
    rows[0] = rows[0].model_copy(update={"ortholog_group": label})
    genome = [
        absent("GL1", label, 4151000),
        absent("GL2", "OG8_1000002", 4150000),
        absent("GR1", "OG8_2000001", 4170000),
    ]

    assert picked(find_anchors(rows, example, genome)) == ("L2", "GL2", "R1", "GR1")


def test_one_gene_on_both_sides_is_no_anchor_pair() -> None:
    rows, example = neighbourhood(1, 1)
    rows[2] = rows[2].model_copy(update={"ortholog_group": "OG8_1000001"})
    genome = [absent("G1", "OG8_1000001", 4150000)]

    assert find_anchors(rows, example, genome) is None


def test_a_gene_on_another_contig_is_no_neighbour() -> None:
    rows, example = neighbourhood(0, 1)
    rows.append(gene("OTHER", 99000, group="OG8_3000000", sequence_id="KQ976400"))
    genome = [
        absent("GO", "OG8_3000000", 4150000),
        absent("GR1", "OG8_2000001", 4170000),
    ]

    assert find_anchors(rows, example, genome) is None


def test_anchors_on_different_contigs_are_none() -> None:
    rows, example = neighbourhood(1, 1)
    genome = [
        absent("GL1", "OG8_1000001", 4150000),
        absent("GR1", "OG8_2000001", 4170000, "TGGT1_chrVIII"),
    ]

    assert find_anchors(rows, example, genome) is None


def test_anchors_more_than_sixty_kilobases_apart_are_none() -> None:
    rows, example = neighbourhood(1, 1)
    near = [
        absent("GL1", "OG8_1000001", 100000),
        absent("GR1", "OG8_2000001", 100899 + ANCHOR_MAX_SPAN),
    ]
    far = [near[0], absent("GR1", "OG8_2000001", 100900 + ANCHOR_MAX_SPAN)]

    anchors = find_anchors(rows, example, near)

    assert anchors is not None
    assert anchors.between == (100899, 100899 + ANCHOR_MAX_SPAN)
    assert find_anchors(rows, example, far) is None


def test_the_span_lies_between_the_anchors_in_either_order() -> None:
    forward = Anchors(
        left=anchor("L1", "GL1", 4150000), right=anchor("R1", "GR1", 4170000)
    )
    reverse = Anchors(left=forward.right, right=forward.left)

    assert forward.between == reverse.between == (4150899, 4170000)


def test_anchors_apart_are_not_anchors() -> None:
    with pytest.raises(ValidationError, match="do not lie on one contig within 60000"):
        Anchors(
            left=anchor("L1", "GL1", 100000),
            right=anchor("R1", "GR1", 100900 + ANCHOR_MAX_SPAN),
        )


def test_the_widest_window_between_anchors_is_within_the_audit_limit() -> None:
    assert ANCHOR_MAX_SPAN + 1 + 2 * MISSING_PAD <= AUDIT_MAX_WINDOW_BASES


def test_the_genes_over_a_span_are_the_ones_it_overlaps() -> None:
    genes = [absent("A", "OG", 1000), absent("B", "OG", 2000), absent("C", "OG", 3000)]

    assert [g.gene for g in overlapping(genes, (1899, 2000))] == ["A", "B"]
    assert overlapping(genes, None) == []


def located(found: int, ns: int = 0, windows: int = 10) -> Located:
    return Located(
        windows=windows,
        found=found,
        span=(1000, 1599) if found else None,
        ns=ns,
    )


@pytest.mark.parametrize(
    ("found", "ns", "overlapping", "verdict"),
    [
        (6, 0, [], "IN_DNA_UNANNOTATED"),
        (10, 500, [], "IN_DNA_UNANNOTATED"),
        (6, 0, [gene("TGGT1_1", 1200, organism=GT1)], "IN_DNA_OTHER_MODEL"),
        (5, 101, [], "GAP"),
        (5, 100, [], "PARTIAL"),
        (4, 0, [], "PARTIAL"),
        (3, 0, [], "NOT_IN_DNA"),
        (0, 101, [], "GAP"),
    ],
)
def test_the_verdict_follows_share_ns_and_overlap(
    found: int, ns: int, overlapping: list[GeneRow], verdict: str
) -> None:
    assert missing_verdict(located(found, ns), overlapping) == verdict


@pytest.mark.parametrize(
    ("found", "windows", "verdict"),
    [
        (7, 20, "PARTIAL"),
        (6, 20, "NOT_IN_DNA"),
        (12, 20, "IN_DNA_UNANNOTATED"),
        (11, 20, "PARTIAL"),
        (119, 200, "PARTIAL"),
        (120, 200, "IN_DNA_UNANNOTATED"),
    ],
)
def test_the_share_bounds_are_inclusive(found: int, windows: int, verdict: str) -> None:
    assert missing_verdict(located(found, windows=windows), []) == verdict


def unanchored() -> dict[str, object]:
    return {
        "verdict": "NO_SYNTENY",
        "gene_ids": [{"given": "TGARI_257090", "resolved": "TGARI_257090"}],
        "example_gene": "TGARI_257090",
        "absent_organism": GT1,
        "example_length": 359,
        "annotated_members": [],
        "anchors": None,
        "located": None,
        "overlapping": None,
        "open_frame": None,
        "stops": None,
        "intact_frame": None,
        "code": None,
        "code_inferred": False,
    }


def anchored() -> dict[str, object]:
    return {
        **unanchored(),
        "verdict": "IN_DNA_UNANNOTATED",
        "anchors": Anchors(
            left=anchor("L1", "GL1", 4150000), right=anchor("R1", "GR1", 4170000)
        ),
        "located": located(6),
        "overlapping": [],
        "stops": [],
        "intact_frame": True,
        "code": "standard",
        "code_inferred": True,
    }


def annotated_in_genome() -> dict[str, object]:
    member = {"gene": "TGGT1_999999", "sequence_id": "TGGT1_chrX", "start": 100000}
    return {
        **unanchored(),
        "verdict": "ANNOTATED_IN_GENOME",
        "annotated_members": [member],
    }


def test_every_shape_of_the_audit_is_valid() -> None:
    assert MissingGeneAudit.model_validate(unanchored()).code_inferred is False
    assert MissingGeneAudit.model_validate(anchored()).code_inferred is True
    annotated = MissingGeneAudit.model_validate(annotated_in_genome())
    assert [m.gene for m in annotated.annotated_members or []] == ["TGGT1_999999"]
    assert (
        MissingGeneAudit.model_validate(
            {**unanchored(), "annotated_members": None}
        ).annotated_members
        is None
    )


@pytest.mark.parametrize(
    "change",
    [
        {"annotated_members": []},
        {"annotated_members": None},
        {"verdict": "NO_SYNTENY"},
    ],
)
def test_annotated_in_genome_and_only_it_names_annotated_members(
    change: dict[str, object],
) -> None:
    with pytest.raises(ValidationError, match="ANNOTATED_IN_GENOME"):
        MissingGeneAudit.model_validate({**annotated_in_genome(), **change})


def test_annotated_in_genome_reads_no_genome() -> None:
    with pytest.raises(ValidationError, match="reads no genome"):
        MissingGeneAudit.model_validate(
            {**annotated_in_genome(), "located": located(6)}
        )


@pytest.mark.parametrize(
    "change",
    [
        {"located": located(6)},
        {"stops": []},
        {"code": "standard"},
        {"code_inferred": True},
        {"overlapping": []},
        {"verdict": "PARTIAL"},
    ],
)
def test_no_synteny_and_only_it_carries_no_genome_fact(
    change: dict[str, object],
) -> None:
    with pytest.raises(ValidationError, match="reads no genome"):
        MissingGeneAudit.model_validate({**unanchored(), **change})


@pytest.mark.parametrize(
    "change",
    [{"stops": None}, {"code": None}, {"overlapping": None}, {"located": None}],
)
def test_a_read_audit_carries_every_genome_fact(change: dict[str, object]) -> None:
    with pytest.raises(ValidationError, match="reads no genome"):
        MissingGeneAudit.model_validate({**anchored(), **change})


def test_the_audit_serves_camel_case() -> None:
    audit = MissingGeneAudit(
        verdict="NO_SYNTENY",
        gene_ids=[GeneId(given="TGARI_257090", resolved="TGARI_257090")],
        example_gene="TGARI_257090",
        absent_organism=GT1,
        example_length=359,
        annotated_members=[],
        anchors=None,
        located=None,
        overlapping=None,
        open_frame=None,
        stops=None,
        intact_frame=None,
        code=None,
        code_inferred=False,
    )

    assert audit.model_dump(by_alias=True) == {
        "verdict": "NO_SYNTENY",
        "geneIds": [{"given": "TGARI_257090", "resolved": "TGARI_257090"}],
        "exampleGene": "TGARI_257090",
        "absentOrganism": GT1,
        "exampleLength": 359,
        "annotatedMembers": [],
        "anchors": None,
        "located": None,
        "overlapping": None,
        "openFrame": None,
        "stops": None,
        "intactFrame": None,
        "code": None,
        "codeInferred": False,
    }


@pytest.mark.parametrize("ids", [[], [{"given": "a", "resolved": "TGARI_2"}]])
def test_an_audit_whose_gene_ids_name_another_gene_is_invalid(
    ids: list[dict[str, str]],
) -> None:
    with pytest.raises(ValidationError, match="geneIds resolve to"):
        MissingGeneAudit.model_validate({**unanchored(), "gene_ids": ids})

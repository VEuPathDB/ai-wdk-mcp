from scripts.record_audit_strain import StrainWire
from tests._support.audit_wire import FIXTURES, answers
from tests._support.proteins import row, tight

from veupathdb_mcp.audit.genes import GeneRow, GroupMember, rows_of
from veupathdb_mcp.audit.lengths import GroupProfile, call_length, classify

YIP1 = "PF3D7_1472100"
NON_CODING = [
    "Htart_000299200",
    "PCHCB_000391400",
    "PKNOH_S110079400",
    "PRG01_1472000",
    "PVSEL_1304000",
    "PYYM_1337000",
    "PfCD01_140077200",
    "PfKE01_140076700",
    "PfSD01_140075200",
]


def yip1_rows() -> list[GeneRow]:
    wire = StrainWire.model_validate_json(
        (FIXTURES / "strain_pfalDd2_yip1.json").read_text()
    )
    return [r for answer in answers(wire.row_answers) for r in rows_of(answer, "x")]


def with_pseudogenes(rows: list[GeneRow]) -> list[GeneRow]:
    return [
        r.model_copy(update={"pseudo": True}) if i % 7 == 3 else r
        for i, r in enumerate(rows)
    ]


def untypical(rows: list[GeneRow]) -> list[tuple[str, str, float | None]]:
    group = [GroupMember.of_row(r) for r in rows]
    calls = {r.gene: call_length([r], group) for r in rows}
    return sorted(
        (gene, call.length_class, call.ratio)
        for gene, call in calls.items()
        if call.length_class != "TYPICAL"
    )


def test_single_calls_on_recorded_rows_equal_the_row_group_calls() -> None:
    rows = yip1_rows()

    assert len(rows) == 62
    assert untypical(rows) == [("PY05360", "SHORT", 0.188)]
    assert classify(rows[0], [GroupMember.of_row(r) for r in rows]) == "TYPICAL"


def test_a_pseudogene_row_with_a_length_is_not_coding_in_the_group() -> None:
    rows = with_pseudogenes(yip1_rows())

    assert sorted(r.gene for r in rows if r.pseudo) == sorted(NON_CODING)
    assert untypical(rows) == sorted(
        [("PY05360", "SHORT", 0.187), *((g, "UNQUALIFIED", None) for g in NON_CODING)]
    )


def test_a_split_on_recorded_rows_equals_the_row_group_call() -> None:
    for rows in (yip1_rows(), with_pseudogenes(yip1_rows())):
        [target] = [r for r in rows if r.gene == YIP1]
        half = (target.protein_length or 0) // 2
        first = target.model_copy(update={"gene": f"{YIP1}_a", "protein_length": half})
        second = target.model_copy(
            update={
                "gene": f"{YIP1}_b",
                "protein_length": (target.protein_length or 0) - half,
                "start": target.end + 100,
                "end": target.end + 900,
            }
        )
        group = [
            GroupMember.of_row(r)
            for r in [*(r for r in rows if r.gene != YIP1), first, second]
        ]

        call = call_length([first, second], group)

        assert (call.length_class, call.ratio, call.expected) == ("SPLIT", 1.075, 292)


def test_a_pseudogene_row_is_no_organism_of_the_profile() -> None:
    pseudogene = row("EXC_0001", "Examplec gamma C", 300).model_copy(
        update={"pseudo": True}
    )
    group = [GroupMember.of_row(r) for r in [*tight(), pseudogene]]

    assert GroupMember.of_row(pseudogene).protein_length is None
    assert GroupProfile.of([], group).organisms == len(tight())

import pytest
from tests._support.audit_site import members
from tests._support.audit_wire import ServedRecords, answers, install_records, load_wire
from tests._support.proteins import row, tight
from tests._support.row_reads import serve_recorded_rows
from tests._support.wdk_genes import serve_private
from veupathdb.wdk import WDKRecordInstance

from veupathdb_mcp.audit import gene_models
from veupathdb_mcp.audit.genes import LOCUS_TAG, GroupMember, orthologs_of, rows_of
from veupathdb_mcp.audit.lengths import GroupProfile, call_length
from veupathdb_mcp.tools import audit_tools

PKAC = "PcyM_0736700"
PKAC_FIXTURE = "pcynM_pkac_length.json"


async def test_a_large_group_is_one_record_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wire = load_wire(PKAC_FIXTURE)
    records = install_records(monkeypatch, wire)
    _, reports = serve_private(monkeypatch, [])

    group = await orthologs_of("plasmodb", PKAC)

    assert len(group.members) == 522
    assert all(m.organism and m.protein_length for m in group.members)
    assert group.members[0].gene == "PBANKA_0104100"
    assert (group.members[0].organism, group.members[0].protein_length) == (
        "Plasmodium berghei ANKA",
        353,
    )
    assert records.reads == [["Orthologs"]]
    assert reports.datasets == []


async def test_the_group_lengths_classify_as_the_gene_rows_did(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wire = load_wire(PKAC_FIXTURE)
    install_records(monkeypatch, wire)
    [me] = rows_of(answers(wire.gene_answers)[0], LOCUS_TAG)
    rows = [
        row
        for answer in answers(wire.row_answers)
        for row in rows_of(answer, LOCUS_TAG)
    ]

    by_table = call_length([me], (await orthologs_of("plasmodb", PKAC)).members)
    lengths = {row.gene: row.protein_length for row in rows if row.gene != PKAC}

    assert {
        m.gene: m.protein_length for m in (await orthologs_of("plasmodb", PKAC)).members
    } == lengths
    assert (by_table.length_class, by_table.ratio) == ("UNQUALIFIED", 0.07)
    assert (by_table.profile.organisms, by_table.profile.median) == (63, 4008)
    assert (by_table.profile.copies, round(by_table.profile.spread, 3)) == (8, 0.092)


async def test_the_length_check_places_only_the_gene_it_checks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wire = load_wire(PKAC_FIXTURE)
    records = install_records(monkeypatch, wire)
    rows = serve_recorded_rows(monkeypatch, wire.gene_answers)
    _, reports = serve_private(monkeypatch, [])

    result = await audit_tools.audit_gene_length("plasmodb", PKAC)

    assert (result.verdict, result.length_class, result.organisms) == (
        "NOT_CHECKED",
        "UNQUALIFIED",
        63,
    )
    assert rows.reads == [PKAC]
    assert records.reads == [["Orthologs"]]
    assert reports.datasets == []


def listed(gene: str, organism: str, length: str) -> dict[str, str]:
    return {
        "ortho_gene_source_id": gene,
        "organism": organism,
        "protein_length": length,
        "gene_product": "protein",
        "is_syntenic": "yes",
        "is_reference_strain": "no",
        "has_comment": "no",
    }


async def test_a_group_lists_neither_its_gene_nor_a_member_twice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    table = ServedRecords(
        [
            WDKRecordInstance.model_validate(
                {
                    "id": [],
                    "attributes": {},
                    "tables": {
                        "Orthologs": [
                            listed("EXA_0001", "Examplea alpha A", "300"),
                            listed("EXB_0001", "Exampleb beta B", "310"),
                            listed("EXB_0001", "Exampleb beta B", "310"),
                        ]
                    },
                }
            )
        ]
    )
    monkeypatch.setattr(gene_models, "get_strategy_api", lambda site_id: table)

    group = await orthologs_of("plasmodb", "EXA_0001")

    assert [(m.gene, m.protein_length) for m in group.members] == [("EXB_0001", 310)]


def test_a_member_with_no_length_is_no_organism_of_the_profile() -> None:
    group = [
        *members(tight()),
        GroupMember.of_row(row("EXC_0001", "Examplec gamma C", None)),
    ]

    assert GroupProfile.of([], group).organisms == 9


def test_a_partner_the_group_does_not_list_is_no_split() -> None:
    me = row("EXA_0001", "Plasmodium speciesM X", 200)
    partner = row("EXA_0002", "Plasmodium speciesM X", 220)

    alone = call_length([me, partner], members(tight()))
    listed_too = call_length([me, partner], members([*tight(), partner]))

    assert (alone.length_class, listed_too.length_class) == ("UNQUALIFIED", "SPLIT")

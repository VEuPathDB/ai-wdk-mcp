from collections.abc import Callable

import pytest
from fastmcp.exceptions import ToolError
from pydantic import ValidationError
from tests._support.anatomy_site import (
    NF54_PAGM,
    NF54_PIGA,
    PAGM,
    PAGM_FILE,
    PIGA,
    PIGA_FILE,
    AnatomySite,
)
from tests._support.audit_site import window_refused
from veupathdb.wdk import WDKRecordInstance

from veupathdb_mcp.audit import served
from veupathdb_mcp.audit.anatomy import Anatomy, pseudogene_anatomy
from veupathdb_mcp.audit.pseudogene import check_pseudogene_call
from veupathdb_mcp.tools import audit_anatomy_tools

PIGA_EXONS = [
    (1063699, 1063980),
    (1064067, 1064156),
    (1064288, 1064329),
    (1064535, 1065602),
    (1065812, 1065985),
]


def with_exons(site: AnatomySite, exons: list[tuple[int, int]]) -> None:
    site.records[NF54_PIGA] = WDKRecordInstance.model_validate(
        {
            "attributes": site.records[NF54_PIGA].attributes,
            "tables": {
                "GeneModelDump": [
                    {
                        "type": "Exon",
                        "transcript_ids": "PfNF54_100037200.1",
                        "sequence_id": "VBRF01000019.1",
                        "strand": "-",
                        "gm_start": str(start),
                        "gm_end": str(end),
                    }
                    for start, end in exons
                ]
            },
        }
    )


async def test_the_piga_pseudogene_gives_five_segments_and_four_junctions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    AnatomySite(monkeypatch, PIGA_FILE)

    result = await audit_anatomy_tools.audit_pseudogene_anatomy(
        "plasmodb", NF54_PIGA, PIGA
    )

    assert result.segments == PIGA_EXONS
    assert [
        (j.after, j.before, j.gap, j.gap_mod_3, j.run_base, j.run_length)
        for j in result.junctions
    ] == [
        (1063980, 1064067, 86, 2, "T", 6),
        (1064156, 1064288, 131, 2, "T", 4),
        (1064329, 1064535, 205, 1, "T", 3),
        (1065602, 1065812, 209, 2, "A", 9),
    ]
    assert [j.ns_within_100 for j in result.junctions] == [0, 0, 0, 0]
    assert (result.to_contig_start, result.to_contig_end) == (1063698, 293757)
    assert result.ns_in_gene == 0
    assert result.reference_segments == 7
    assert result.dna_check.verdict == "INTACT"
    assert result.dna_check.strain_cds_length == 1386
    assert (result.strain_gene, result.reference_gene) == (NF54_PIGA, PIGA)


async def test_the_pagm_pseudogene_gives_one_segment_and_no_junction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    AnatomySite(monkeypatch, PAGM_FILE)

    result = await audit_anatomy_tools.audit_pseudogene_anatomy(
        "plasmodb", NF54_PAGM, PAGM
    )

    assert result.segments == [(1073290, 1076112)]
    assert result.junctions == []
    assert (result.to_contig_start, result.to_contig_end) == (1073289, 763215)
    assert result.reference_segments == 1
    assert result.dna_check.verdict == "INTACT"
    assert result.dna_check.reference_cds_length == 2823


async def test_the_anatomy_reads_the_padded_strain_window_and_each_record_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = AnatomySite(monkeypatch, PIGA_FILE)

    await audit_anatomy_tools.audit_pseudogene_anatomy("plasmodb", NF54_PIGA, PIGA)

    assert site.record_asks == [
        (PIGA, ["organismAbbrev"], ["GeneModelDump"]),
        (NF54_PIGA, ["organismAbbrev"], ["GeneModelDump"]),
    ]
    assert (site.models_read, site.organisms_read) == ([], [])
    assert site.windows == [
        ("pfal3D7", "Pf3D7_10_v3", 1302298, 1305315),
        ("pfalNF54", "VBRF01000019.1", 1060699, 1068985),
    ]
    assert site.windows[-1] == ("pfalNF54", "VBRF01000019.1", 1060699, 1068985)
    assert site.lengths_read == [("pfalNF54", "VBRF01000019.1")]


async def test_the_anatomy_is_served_in_camel_case(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    AnatomySite(monkeypatch, PIGA_FILE)

    result = await audit_anatomy_tools.audit_pseudogene_anatomy(
        "plasmodb", NF54_PIGA, PIGA
    )
    served_result = result.model_dump(by_alias=True, mode="json")

    assert served_result["junctions"][3] == {
        "after": 1065602,
        "before": 1065812,
        "gap": 209,
        "gapMod3": 2,
        "runBase": "A",
        "runLength": 9,
        "nsWithin100": 0,
    }
    assert served_result["dnaCheck"]["verdict"] == "INTACT"
    assert served_result["referenceSegments"] == 7
    assert served_result["toContigEnd"] == 293757
    assert served_result["segments"][0] == [1063699, 1063980]


async def test_an_unknown_strain_gene_is_a_tool_error_before_any_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = AnatomySite(monkeypatch, PIGA_FILE)

    with pytest.raises(ToolError, match="PfNF54_9 names no gene of plasmodb"):
        await audit_anatomy_tools.audit_pseudogene_anatomy("plasmodb", "PfNF54_9", PIGA)

    assert site.record_asks == []
    assert site.windows == []


async def test_a_strain_model_without_exon_rows_is_a_tool_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = AnatomySite(monkeypatch, PIGA_FILE)
    with_exons(site, [])

    with pytest.raises(ToolError, match=f"{NF54_PIGA} has no Exon rows"):
        await audit_anatomy_tools.audit_pseudogene_anatomy("plasmodb", NF54_PIGA, PIGA)

    assert site.lengths_read == []


async def test_a_strain_window_over_the_limit_is_a_tool_error_before_any_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = AnatomySite(monkeypatch, PIGA_FILE)
    [strain] = [row for row in site.rows if row.gene == NF54_PIGA]
    longer = strain.model_copy(
        update={"end": strain.start + served.AUDIT_MAX_WINDOW_BASES}
    )
    site.rows = [longer if row.gene == NF54_PIGA else row for row in site.rows]
    length = served.AUDIT_MAX_WINDOW_BASES + 1 + 2 * served.PSEUDOGENE_PAD

    with pytest.raises(ToolError, match=window_refused(NF54_PIGA, length)):
        await audit_anatomy_tools.audit_pseudogene_anatomy("plasmodb", NF54_PIGA, PIGA)

    assert (site.record_asks, site.windows) == ([], [])


async def test_exon_rows_outside_the_read_window_are_a_tool_error_before_any_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = AnatomySite(monkeypatch, PIGA_FILE)
    with_exons(site, [(1063699, 1063800), (1070000, 1070100)])

    with pytest.raises(
        ToolError,
        match=f"^{NF54_PIGA} serves Exon rows 1063699-1070100 outside its gene span "
        "1063699-1065985 and the 3000 bases read on each side$",
    ):
        await audit_anatomy_tools.audit_pseudogene_anatomy("plasmodb", NF54_PIGA, PIGA)

    assert (site.windows, site.lengths_read) == ([], [])


@pytest.mark.parametrize(
    ("exons", "named"),
    [
        (
            [(1063699, 1064000), (1063900, 1064100)],
            "1063699-1064000 and 1063900-1064100",
        ),
        (
            [(1063699, 1064000), (1063699, 1064000)],
            "1063699-1064000 and 1063699-1064000",
        ),
    ],
)
async def test_overlapping_exon_rows_are_a_tool_error_naming_them(
    monkeypatch: pytest.MonkeyPatch, exons: list[tuple[int, int]], named: str
) -> None:
    site = AnatomySite(monkeypatch, PIGA_FILE)
    with_exons(site, exons)

    with pytest.raises(ToolError, match=f"{NF54_PIGA} serves Exon rows {named}"):
        await audit_anatomy_tools.audit_pseudogene_anatomy("plasmodb", NF54_PIGA, PIGA)

    assert site.lengths_read == []


async def test_a_reference_record_without_location_attributes_is_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = AnatomySite(monkeypatch, PIGA_FILE)
    site.records[PIGA] = WDKRecordInstance.model_validate(
        {
            "attributes": {"organismAbbrev": "pfal3D7"},
            "tables": site.records[PIGA].tables,
        }
    )

    result = await audit_anatomy_tools.audit_pseudogene_anatomy(
        "plasmodb", NF54_PIGA, PIGA
    )

    assert result.reference_segments == 7
    assert result.dna_check.verdict == "INTACT"


async def test_a_reference_record_without_an_organism_is_a_tool_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = AnatomySite(monkeypatch, PIGA_FILE)
    site.records[PIGA] = WDKRecordInstance.model_validate(
        {"attributes": {}, "tables": site.records[PIGA].tables}
    )

    with pytest.raises(ToolError, match=f"gene record of {PIGA} on plasmodb"):
        await audit_anatomy_tools.audit_pseudogene_anatomy("plasmodb", NF54_PIGA, PIGA)

    assert site.windows == []


async def test_the_anatomy_and_the_dna_check_run_in_a_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    AnatomySite(monkeypatch, PIGA_FILE)
    ran: list[object] = []

    async def in_a_slot[**P, T](
        check: Callable[P, T], *args: P.args, **kwargs: P.kwargs
    ) -> T:
        ran.append(check)
        return check(*args, **kwargs)

    monkeypatch.setattr(audit_anatomy_tools, "run_in_a_slot", in_a_slot)

    await audit_anatomy_tools.audit_pseudogene_anatomy("plasmodb", NF54_PIGA, PIGA)

    assert ran == [pseudogene_anatomy, check_pseudogene_call]


async def test_an_anatomy_whose_gene_ids_swap_its_genes_is_invalid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    AnatomySite(monkeypatch, PIGA_FILE)
    served = (
        await audit_anatomy_tools.audit_pseudogene_anatomy("plasmodb", NF54_PIGA, PIGA)
    ).model_dump()

    with pytest.raises(ValidationError, match="geneIds resolve to"):
        Anatomy.model_validate(
            {**served, "strain_gene": PIGA, "reference_gene": NF54_PIGA}
        )

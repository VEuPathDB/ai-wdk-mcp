from collections.abc import Callable

import pytest
from fastmcp.exceptions import ToolError
from tests._support.fusion_site import (
    BESIDE_REFERENCE,
    DD2,
    MEMBER,
    MEMBER_PRODUCT,
    NEIGHBOUR,
    PARTNER_COPY,
    PARTNER_GROUP,
    PARTNER_PRODUCT,
    PF3D7,
    REFERENCE,
    REFERENCE_GENE,
    UNRELATED,
    fusion_site,
)

from veupathdb_mcp.audit.fusion import check_fusion
from veupathdb_mcp.tools import audit_fusion_tools
from veupathdb_mcp.tools.audit_fusion_tools import audit_gene_fusion

PARTNER = BESIDE_REFERENCE[2]


async def test_a_long_model_whose_extra_residues_match_the_reference_neighbour(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = fusion_site(monkeypatch, REFERENCE + NEIGHBOUR)

    result = await audit_gene_fusion("plasmodb", MEMBER)

    assert (result.genes, result.length_class, result.ratio) == (
        [MEMBER],
        "LONG",
        1.667,
    )
    assert result.reference_gene == REFERENCE_GENE
    assert result.fusion is not None
    assert result.fusion.verdict == "EXTRA_MATCHES_NEIGHBOUR"
    assert (result.fusion.extra, result.fusion.extra_windows) == ([(111, 200)], 8)
    assert (
        result.fusion.partner,
        result.fusion.closest_neighbour,
        result.fusion.neighbour_windows,
    ) == (PARTNER, None, 7)
    assert result.fusion.neighbours == BESIDE_REFERENCE
    assert (result.fusion.product, result.fusion.partner_product) == (
        MEMBER_PRODUCT,
        PARTNER_PRODUCT,
    )
    assert result.fusion.partner_group == PARTNER_GROUP
    assert result.fusion.partner_copies == [PARTNER_COPY]
    assert site.orthologs_read == [MEMBER]
    assert site.proteins_read == [MEMBER, REFERENCE_GENE, *BESIDE_REFERENCE]
    assert site.genomes_read == [PF3D7, DD2]
    assert site.models_read == [REFERENCE_GENE, PARTNER]
    assert [m.gene for m in result.models] == [REFERENCE_GENE, PARTNER]
    assert result.merged is not None
    assert (result.merged.gene, result.merged.seqid, result.merged.start) == (
        MEMBER,
        "PfDd2_01",
        50001,
    )


async def test_a_partner_model_with_no_exon_row_is_not_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = fusion_site(monkeypatch, REFERENCE + NEIGHBOUR)
    site.exonless.add(PARTNER)

    result = await audit_gene_fusion("plasmodb", MEMBER)

    assert result.fusion is not None
    assert (result.fusion.verdict, result.fusion.partner) == (
        "EXTRA_MATCHES_NEIGHBOUR",
        PARTNER,
    )
    assert site.models_read == [REFERENCE_GENE, PARTNER]
    assert [m.gene if m else None for m in result.models] == [REFERENCE_GENE, None]
    assert result.evidence_unread == [
        f"the GeneModelDump of {PARTNER} gives no Exon row for {PARTNER}.1"
    ]
    assert result.merged is not None


async def test_a_long_model_whose_extra_residues_no_neighbour_holds_is_unexplained(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = fusion_site(monkeypatch, REFERENCE + UNRELATED)

    result = await audit_gene_fusion("plasmodb", MEMBER)

    assert result.fusion is not None
    assert result.fusion.verdict == "EXTRA_UNEXPLAINED"
    assert (
        result.fusion.partner,
        result.fusion.closest_neighbour,
        result.fusion.neighbour_windows,
    ) == (None, None, 0)
    assert site.models_read == [REFERENCE_GENE]
    assert [m.gene for m in result.models] == [REFERENCE_GENE]
    assert (result.fusion.product, result.fusion.partner_product) == (
        MEMBER_PRODUCT,
        None,
    )
    assert (result.fusion.partner_group, result.fusion.partner_copies) == (
        None,
        None,
    )
    assert site.genomes_read == [PF3D7]


async def test_a_neighbour_with_too_few_windows_is_the_closest_and_reads_no_copies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = fusion_site(monkeypatch, REFERENCE + UNRELATED[:60] + NEIGHBOUR[:30])

    result = await audit_gene_fusion("plasmodb", MEMBER)

    assert result.fusion is not None
    assert result.fusion.verdict == "EXTRA_UNEXPLAINED"
    assert (
        result.fusion.partner,
        result.fusion.closest_neighbour,
        result.fusion.neighbour_windows,
    ) == (None, PARTNER, 2)
    assert (
        result.fusion.partner_group,
        result.fusion.partner_product,
        result.fusion.partner_copies,
    ) == (None, None, None)
    assert site.genomes_read == [PF3D7]


async def test_a_partner_in_a_residual_group_reads_no_copies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = fusion_site(monkeypatch, REFERENCE + NEIGHBOUR, partner_group="OGR7r1_1")

    result = await audit_gene_fusion("plasmodb", MEMBER)

    assert result.fusion is not None
    assert result.fusion.verdict == "EXTRA_MATCHES_NEIGHBOUR"
    assert (result.fusion.partner_group, result.fusion.partner_copies) == (
        "OGR7r1_1",
        None,
    )
    assert site.genomes_read == [PF3D7]


async def test_a_gene_that_is_not_long_answers_its_class_and_reads_nothing_more(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = fusion_site(monkeypatch, REFERENCE)

    result = await audit_gene_fusion("plasmodb", MEMBER)

    assert (result.length_class, result.ratio, result.fusion) == ("TYPICAL", 1.0, None)
    assert (result.organisms, result.group_median) == (10, 120)
    assert result.reference_gene == REFERENCE_GENE
    assert (site.proteins_read, site.genomes_read) == ([], [])


async def test_a_group_the_length_check_cannot_judge_answers_unqualified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = fusion_site(monkeypatch, REFERENCE + NEIGHBOUR, relatives=5)

    result = await audit_gene_fusion("plasmodb", MEMBER)

    assert (result.length_class, result.organisms, result.fusion) == (
        "UNQUALIFIED",
        7,
        None,
    )
    assert (site.proteins_read, site.genomes_read) == ([], [])


async def test_an_unknown_gene_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    fusion_site(monkeypatch, REFERENCE + NEIGHBOUR)

    with pytest.raises(ToolError, match="PfDd2_9 names no gene of plasmodb"):
        await audit_gene_fusion("plasmodb", "PfDd2_9")


async def test_a_long_gene_without_a_protein_is_refused_before_a_genome_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = fusion_site(monkeypatch, REFERENCE + NEIGHBOUR)
    del site.proteins[MEMBER]

    with pytest.raises(ToolError, match=f"{MEMBER} has no protein on plasmodb"):
        await audit_gene_fusion("plasmodb", MEMBER)

    assert site.genomes_read == []


async def test_a_reference_its_genome_report_lacks_is_a_tool_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = fusion_site(monkeypatch, REFERENCE + NEIGHBOUR)
    site.genomes[PF3D7] = [r for r in site.genomes[PF3D7] if r.gene != REFERENCE_GENE]

    with pytest.raises(ToolError, match=f"3D7 on plasmodb lists no {REFERENCE_GENE}$"):
        await audit_gene_fusion("plasmodb", MEMBER)


async def test_the_fusion_check_runs_in_a_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fusion_site(monkeypatch, REFERENCE + NEIGHBOUR)
    ran: list[object] = []

    async def in_a_slot[**P, T](
        check: Callable[P, T], *args: P.args, **kwargs: P.kwargs
    ) -> T:
        ran.append(check)
        return check(*args, **kwargs)

    monkeypatch.setattr(audit_fusion_tools, "run_in_a_slot", in_a_slot)

    await audit_gene_fusion("plasmodb", MEMBER)

    assert ran == [check_fusion]

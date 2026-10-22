import pytest
from fastmcp.exceptions import ToolError
from tests._support.audit_site import window_refused
from tests._support.proteins import PROTEIN, back_translate
from tests._support.strain_site import (
    INSERT,
    REFERENCE,
    STRAIN,
    StrainSite,
    strain_site,
)

from veupathdb_mcp.audit import served
from veupathdb_mcp.audit.codes import GeneticCode
from veupathdb_mcp.audit.gene_models import GeneModel
from veupathdb_mcp.tools.audit_strain_tools import audit_strain_model

SHORT = PROTEIN[:60] + PROTEIN[140:]
LONG = PROTEIN[:100] + INSERT + PROTEIN[100:]


def short_strain(monkeypatch: pytest.MonkeyPatch, *, left: int = 40000) -> StrainSite:
    return strain_site(
        monkeypatch,
        (SHORT, PROTEIN),
        intron=back_translate(PROTEIN[60:140]),
        left=left,
    )


async def test_a_strain_that_lost_a_segment_its_genome_encodes_is_strain_short(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = short_strain(monkeypatch)
    strain = site.rows[0]

    result = await audit_strain_model("plasmodb", STRAIN, REFERENCE)

    assert (result.lost, result.extra) == ([(61, 140)], [])
    assert result.dna.verdict == "GENOME_ENCODES"
    assert result.dna.counts == {"model": 12, "genome_same_strand": 7}
    assert result.dna.track == "MMMMMMGGGGGGGMMMMMM"
    assert (result.side, result.relatives.median) == ("STRAIN_SHORT", 200)
    assert (result.not_read, result.nearby_paralogs) == (None, [])
    assert (result.relatives.tier, result.relatives.copies_per_organism) == (
        "SAME_GENUS",
        1,
    )
    assert [(m.organism, m.length) for m in result.relatives.members] == [
        (f"Plasmodium species{i} X", 200) for i in range(8)
    ]
    assert (result.strain_length, result.reference_length) == (120, 200)
    assert (result.code, result.code_inferred) == (GeneticCode.STANDARD, True)
    assert (result.dna.ns_in_window, result.dna.at_contig_edge) == (0, False)
    assert site.orthologs_read == [REFERENCE]
    assert site.models_read == [STRAIN, REFERENCE]
    assert [(m.gene, m.cds) for m in result.models] == [
        (STRAIN, [(p.start, p.end) for p in site.models[STRAIN].cds]),
        (REFERENCE, [(site.rows[1].start, site.rows[1].end)]),
    ]
    assert site.proteins_read == [STRAIN, REFERENCE]
    assert site.rows_read == [STRAIN, REFERENCE]
    assert site.windows == [
        ("pfalDd2", strain.sequence_id, strain.start - 6000, strain.end + 6000)
    ]


async def test_a_strain_model_with_no_cds_row_is_checked_and_not_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = short_strain(monkeypatch)
    site.models[STRAIN] = GeneModel(organism_abbrev="pfalDd2", cds=[])

    result = await audit_strain_model("plasmodb", STRAIN, REFERENCE)

    assert (result.dna.verdict, result.side) == ("GENOME_ENCODES", "STRAIN_SHORT")
    assert (result.code, result.code_inferred) == (GeneticCode.STANDARD, False)
    assert site.models_read == [STRAIN, REFERENCE]
    assert result.models[0] is None
    assert [m.gene for m in result.models[1:] if m] == [REFERENCE]
    assert result.evidence_unread == [f"the GeneModelDump of {STRAIN} gives no CDS row"]


async def test_a_reference_model_with_no_cds_row_is_not_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = short_strain(monkeypatch)
    site.models[REFERENCE] = GeneModel(organism_abbrev="pfal3D7", cds=[])

    result = await audit_strain_model("plasmodb", STRAIN, REFERENCE)

    assert result.dna.verdict == "GENOME_ENCODES"
    assert [m.gene if m else None for m in result.models] == [STRAIN, None]
    assert result.evidence_unread == [
        f"the GeneModelDump of {REFERENCE} gives no CDS row"
    ]


async def test_a_segment_the_strain_genome_lacks_is_absent_and_not_judged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = strain_site(monkeypatch, (PROTEIN, LONG))
    strain = site.rows[0]

    result = await audit_strain_model("plasmodb", STRAIN, REFERENCE)

    assert (result.lost, result.extra) == ([(101, 140)], [])
    assert result.dna.verdict == "ABSENT"
    assert result.dna.counts == {"model": 20, "absent": 3}
    assert (result.side, result.relatives.median) == ("NOT_JUDGED", 200)
    assert (result.strain_length, result.reference_length) == (200, 240)
    assert site.windows == [
        ("pfalDd2", strain.sequence_id, strain.start - 6000, strain.end + 6000)
    ]


async def test_a_lost_segment_beside_a_contig_end_is_assembly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = strain_site(monkeypatch, (PROTEIN, LONG), left=1000)

    result = await audit_strain_model("plasmodb", STRAIN, REFERENCE)

    assert (result.dna.verdict, result.side) == ("ASSEMBLY", "NOT_JUDGED")
    assert result.dna.at_contig_edge
    assert site.lengths_read == [("pfalDd2", site.rows[0].sequence_id)]


async def test_a_strain_that_only_gained_a_segment_reads_no_genome(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = strain_site(monkeypatch, (LONG, PROTEIN))

    result = await audit_strain_model("plasmodb", STRAIN, REFERENCE)

    assert (result.lost, result.extra) == ([], [(101, 140)])
    assert (result.dna.verdict, result.dna.windows, result.dna.track) == (
        "NOT_CHECKED",
        0,
        "",
    )
    assert (result.dna.ns_in_window, result.dna.at_contig_edge) == (None, None)
    assert (result.code, result.code_inferred) == (None, False)
    assert (result.not_read, result.side) == ("NO_LOST_RUN", "NOT_JUDGED")
    assert result.relatives.median == 200
    assert site.models_read == []
    assert site.windows == []
    assert site.lengths_read == []


async def test_a_residual_group_pair_is_unqualified_and_reads_no_genome(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = short_strain(monkeypatch)
    site.rows = [
        r.model_copy(update={"ortholog_group": "OGR7_0000001"}) for r in site.rows
    ]

    result = await audit_strain_model("plasmodb", STRAIN, REFERENCE)

    assert (result.lost, result.not_read) == ([(61, 140)], "UNQUALIFIED")
    assert (result.dna.verdict, result.side) == ("NOT_CHECKED", "NOT_JUDGED")
    assert (result.relatives.missing, result.relatives.median) == (
        "RESIDUAL_GROUP",
        None,
    )
    assert site.orthologs_read == []
    assert site.models_read == []
    assert site.windows == []


async def test_a_group_with_paralogs_has_no_relatives(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = short_strain(monkeypatch)
    paralogs = [
        r.model_copy(
            update={"gene": f"{r.gene}b", "protein_length": 900, "sequence_id": "b"}
        )
        for r in site.rows
    ]
    site.orthologs[REFERENCE] = [*site.rows, *paralogs]

    result = await audit_strain_model("plasmodb", STRAIN, REFERENCE)

    assert (result.dna.verdict, result.side) == ("GENOME_ENCODES", "NO_RELATIVES")
    assert (result.relatives.missing, result.relatives.copies_per_organism) == (
        "PARALOGS",
        2,
    )
    assert (result.relatives.members, result.relatives.median) == ([], None)


async def test_a_group_with_one_other_species_has_no_relatives(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    strain_site(
        monkeypatch,
        (SHORT, PROTEIN),
        intron=back_translate(PROTEIN[60:140]),
        relatives=1,
    )

    result = await audit_strain_model("plasmodb", STRAIN, REFERENCE)

    assert (result.side, result.relatives.median) == ("NO_RELATIVES", None)
    assert result.relatives.missing == "FEWER_THAN_TWO"


async def test_a_pair_that_names_one_gene_twice_is_a_tool_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = short_strain(monkeypatch)

    with pytest.raises(ToolError, match="the pair names PF3D7_1 twice"):
        await audit_strain_model("plasmodb", REFERENCE, REFERENCE)

    assert site.proteins_read == []


async def test_an_unknown_strain_gene_is_a_tool_error_naming_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    short_strain(monkeypatch)

    with pytest.raises(ToolError, match="PfDd2_9 names no gene of plasmodb"):
        await audit_strain_model("plasmodb", "PfDd2_9", REFERENCE)


async def test_genes_of_two_species_are_a_tool_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = short_strain(monkeypatch)
    site.rows[0] = site.rows[0].model_copy(update={"organism": "Plasmodium vivax P01"})

    with pytest.raises(
        ToolError,
        match=(
            r"PfDd2_1 \(Plasmodium vivax P01\) and PF3D7_1 \(Plasmodium falciparum "
            r"3D7\) are not strains of one species"
        ),
    ):
        await audit_strain_model("plasmodb", STRAIN, REFERENCE)

    assert site.proteins_read == []


async def test_two_genes_of_one_genome_are_a_tool_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = short_strain(monkeypatch)
    site.rows[0] = site.rows[0].model_copy(
        update={"organism": "Plasmodium falciparum 3D7"}
    )

    with pytest.raises(
        ToolError,
        match=(
            "PfDd2_1 and PF3D7_1 are both genes of Plasmodium falciparum 3D7; "
            "a strain gene is read against another strain of its species"
        ),
    ):
        await audit_strain_model("plasmodb", STRAIN, REFERENCE)

    assert site.proteins_read == []


async def test_genes_of_two_ortholog_groups_are_a_tool_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = short_strain(monkeypatch)
    site.rows[0] = site.rows[0].model_copy(update={"ortholog_group": "OG7_0000002"})

    with pytest.raises(
        ToolError,
        match=(
            "PfDd2_1 lies in OG7_0000002 and PF3D7_1 in OG7_0000001; a strain gene "
            "is read against a member of its own ortholog group"
        ),
    ):
        await audit_strain_model("plasmodb", STRAIN, REFERENCE)

    assert site.proteins_read == []


async def test_a_strain_gene_without_a_protein_is_a_tool_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = short_strain(monkeypatch)
    del site.proteins[STRAIN]

    with pytest.raises(ToolError, match="PfDd2_1 has no protein on plasmodb"):
        await audit_strain_model("plasmodb", STRAIN, REFERENCE)

    assert site.orthologs_read == []


async def test_a_strain_window_over_the_limit_is_a_tool_error_before_any_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = short_strain(monkeypatch)
    strain = site.rows[0]
    site.rows[0] = strain.model_copy(
        update={"end": strain.start + served.AUDIT_MAX_WINDOW_BASES}
    )
    length = served.AUDIT_MAX_WINDOW_BASES + 1 + 2 * 6000

    with pytest.raises(ToolError, match=window_refused(STRAIN, length)):
        await audit_strain_model("plasmodb", STRAIN, REFERENCE)

    assert site.models_read == []
    assert site.windows == []
    assert site.lengths_read == []


async def test_a_pair_in_no_ortholog_group_is_a_tool_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = short_strain(monkeypatch)
    site.rows = [
        r.model_copy(
            update={"ortholog_group": "N/A (orthology not determined for pseudogenes)"}
        )
        for r in site.rows
    ]

    with pytest.raises(
        ToolError,
        match=(
            r"PfDd2_1 and PF3D7_1 lie in no ortholog group \(N/A \(orthology not "
            r"determined for pseudogenes\)\); a strain gene is read against a "
            r"member of its own ortholog group"
        ),
    ):
        await audit_strain_model("plasmodb", STRAIN, REFERENCE)

    assert site.proteins_read == []

import httpx
import pytest
from fastmcp.exceptions import ToolError
from tests._support.audit_fixtures import (
    GT1_SELK,
    ME49_SELK,
    NF54_PIGA,
    NF54_PIGA_ID,
    PIGA,
    piga_inputs,
    selk_inputs,
)
from tests._support.audit_site import window_refused
from tests._support.piga_selk_site import (
    SELK_PAD,
    Site,
    gt1_selk_row,
    reference_piga_row,
    strain_piga_row,
)
from veupathdb.errors import DataParsingError
from veupathdb.jbrowse import GenomeIndexError, JBrowseError
from veupathdb.wdk import WDKRecordInstance

from veupathdb_mcp.audit import gene_models, served
from veupathdb_mcp.audit.gene_ids import GeneReads
from veupathdb_mcp.audit.gene_models import GeneModel
from veupathdb_mcp.tools import audit_tools


async def test_the_pseudogene_tool_returns_the_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(audit_tools, "pseudogene_inputs", piga_inputs)

    result = await audit_tools.audit_pseudogene_call("plasmodb", NF54_PIGA, PIGA)

    assert result.verdict == "INTACT"
    assert result.strain_cds_length == result.reference_cds_length == 1386
    assert (result.strain_gene, result.reference_gene) == (NF54_PIGA_ID, PIGA)
    assert [(i.given, i.resolved) for i in result.gene_ids] == [
        (NF54_PIGA, NF54_PIGA_ID),
        (PIGA, PIGA),
    ]


async def test_the_selenoprotein_tool_returns_the_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(audit_tools, "selenoprotein_inputs", selk_inputs)

    result = await audit_tools.audit_selenoprotein_end("toxodb", GT1_SELK, ME49_SELK)

    assert result.verdict == "STOPS_AT_SEC"
    assert result.reference_tail == "UG"
    assert (result.tail_identity, result.sec_aligned) == (1.0, True)
    assert (result.gene, result.reference_gene) == (GT1_SELK, ME49_SELK)


async def test_a_refused_input_is_a_tool_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(audit_tools, "pseudogene_inputs", piga_inputs)

    with pytest.raises(ToolError, match="NOT_A_GENE names no gene"):
        await audit_tools.audit_pseudogene_call("plasmodb", "NOT_A_GENE", PIGA)


async def test_the_pseudogene_inputs_are_read_on_each_genes_own_strand(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = Site(monkeypatch)

    result = await audit_tools.audit_pseudogene_call("plasmodb", NF54_PIGA, PIGA)

    assert result.verdict == "INTACT"
    assert result.strain_cds_length == result.reference_cds_length == 1386
    assert result.residue_differences == 0
    assert site.windows == [
        ("pfal3D7", "Pf3D7_10_v3", 1302298, 1305315),
        ("pfalNF54", "VBRF01000019.1", 1060699, 1068985),
    ]


async def test_the_selenoprotein_inputs_pad_the_gene_past_the_reference_tail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = Site(monkeypatch)

    result = await audit_tools.audit_selenoprotein_end("toxodb", GT1_SELK, ME49_SELK)

    assert result.verdict == "STOPS_AT_SEC"
    assert result.after_model_end.startswith("*G*")
    assert site.windows == [("tgonGT1", "TGGT1_chrXI", 5359280, 5361636)]
    assert (site.models_read, site.organisms_read) == ([], [GT1_SELK])
    assert site.proteins_read == [GT1_SELK, ME49_SELK]


@pytest.mark.parametrize("strand", ["+", "-"])
async def test_the_selenoprotein_window_holds_a_long_tail_after_sec(
    monkeypatch: pytest.MonkeyPatch, strand: str
) -> None:
    site = Site(monkeypatch)
    tail = "U" + "G" * 400
    site.proteins[ME49_SELK] = "MKLVCGGGG" + tail
    gene = gt1_selk_row().model_copy(update={"strand": strand})
    site.rows[2] = gene

    await audit_tools.audit_selenoprotein_end("toxodb", GT1_SELK, ME49_SELK)

    [(_, _, start, end)] = site.windows
    assert gene.start - start >= 3 * len(tail)
    assert end - gene.end >= 3 * len(tail)


async def test_a_reference_without_sec_is_a_tool_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = Site(monkeypatch)
    site.proteins[ME49_SELK] = site.proteins[ME49_SELK].replace("U", "C")

    with pytest.raises(
        ToolError, match="TGME49_316600 has no selenocysteine on toxodb"
    ):
        await audit_tools.audit_selenoprotein_end("toxodb", GT1_SELK, ME49_SELK)

    assert site.models_read == []
    assert site.windows == []


async def test_a_pair_too_long_to_align_is_a_tool_error_naming_both_lengths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = Site(monkeypatch)
    reference = reference_piga_row()
    site.rows[1] = reference.model_copy(update={"end": reference.start + 39999})
    strain = strain_piga_row()
    strain_length = strain.end - strain.start + 1 + 2 * served.PSEUDOGENE_PAD

    with pytest.raises(ToolError, match=f"40000 .*{strain_length} "):
        await audit_tools.audit_pseudogene_call("plasmodb", NF54_PIGA, PIGA)

    assert 40000 * strain_length > served.PSEUDOGENE_MAX_CELLS
    assert site.models_read == []
    assert site.windows == []


async def test_the_longest_pair_under_the_limit_is_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = Site(monkeypatch)
    strain = strain_piga_row()
    strain_length = strain.end - strain.start + 1 + 2 * served.PSEUDOGENE_PAD
    reference = reference_piga_row()
    longest = served.PSEUDOGENE_MAX_CELLS // strain_length
    site.rows[1] = reference.model_copy(update={"end": reference.start + longest - 1})

    await served.pseudogene_inputs("plasmodb", NF54_PIGA, PIGA)

    assert site.windows[0] == (
        "pfal3D7",
        "Pf3D7_10_v3",
        reference.start,
        reference.start + longest - 1,
    )


async def test_a_site_that_does_not_answer_is_a_tool_error_naming_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = Site(monkeypatch)
    site.refusal = httpx.ConnectTimeout("timed out")

    with pytest.raises(ToolError, match="plasmodb did not answer"):
        await audit_tools.audit_pseudogene_call("plasmodb", NF54_PIGA, PIGA)


async def test_an_unknown_gene_is_a_tool_error_naming_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = Site(monkeypatch)

    with pytest.raises(ToolError, match="PF3D7_9999999 names no gene of plasmodb"):
        await audit_tools.audit_pseudogene_call("plasmodb", "PF3D7_9999999", PIGA)

    assert site.models_read == []
    assert site.windows == []


async def test_an_unknown_selenoprotein_reference_is_a_tool_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = Site(monkeypatch)

    with pytest.raises(ToolError, match="TGME49_999999 names no gene of toxodb"):
        await audit_tools.audit_selenoprotein_end("toxodb", GT1_SELK, "TGME49_999999")

    assert site.windows == []


async def test_a_reference_without_cds_rows_is_a_tool_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = Site(monkeypatch)
    site.models[PIGA] = GeneModel(organism_abbrev="pfal3D7", cds=[])

    with pytest.raises(ToolError, match="PF3D7_1032400 has no CDS"):
        await audit_tools.audit_pseudogene_call("plasmodb", NF54_PIGA, PIGA)

    assert site.windows == []


async def test_a_gene_without_a_protein_is_a_tool_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = Site(monkeypatch)
    del site.proteins[ME49_SELK]

    with pytest.raises(ToolError, match="TGME49_316600 has no protein on toxodb"):
        await audit_tools.audit_selenoprotein_end("toxodb", GT1_SELK, ME49_SELK)

    assert site.windows == []


@pytest.mark.parametrize(
    ("refusal", "named"),
    [
        (
            JBrowseError("GET", "https://qa.plasmodb.org/store", 500),
            "https://qa.plasmodb.org/store answered 500",
        ),
        (
            GenomeIndexError("the genome index of pfal3D7 has no sequence Pf3D7_10_v3"),
            "has no sequence Pf3D7_10_v3",
        ),
    ],
)
async def test_a_genome_read_refusal_is_a_tool_error(
    monkeypatch: pytest.MonkeyPatch, refusal: Exception, named: str
) -> None:
    site = Site(monkeypatch)
    site.refusal = refusal

    with pytest.raises(ToolError, match=named):
        await audit_tools.audit_pseudogene_call("plasmodb", NF54_PIGA, PIGA)


async def test_a_wdk_refusal_is_a_tool_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = Site(monkeypatch)

    async def truncated(site_id: str, gene_ids: list[str]) -> GeneReads:
        msg = "WDK GeneByLocusTag report served 1 records of a total of 2"
        raise DataParsingError(msg)

    monkeypatch.setattr(served, "rows_and_proteins", truncated)

    with pytest.raises(ToolError, match="served 1 records of a total of 2"):
        await audit_tools.audit_selenoprotein_end("toxodb", GT1_SELK, ME49_SELK)

    assert site.windows == []


async def test_a_gene_record_without_an_organism_is_a_tool_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = Site(monkeypatch)

    class Records:
        async def get_single_record(
            self,
            record_type: str,
            primary_key: list[dict[str, str]],
            *,
            attributes: list[str],
            tables: list[str],
        ) -> WDKRecordInstance:
            return WDKRecordInstance.model_validate(
                {"attributes": {"organismAbbrev": ""}, "tables": {}}
            )

    monkeypatch.setattr(served, "gene_organism", gene_models.gene_organism)
    monkeypatch.setattr(gene_models, "get_strategy_api", lambda site_id: Records())

    with pytest.raises(ToolError, match="gene record of TGGT1_316600 on toxodb"):
        await audit_tools.audit_selenoprotein_end("toxodb", GT1_SELK, ME49_SELK)

    assert site.windows == []


async def test_a_selenoprotein_window_over_the_limit_is_a_tool_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = Site(monkeypatch)
    gene = gt1_selk_row()
    site.rows[2] = gene.model_copy(
        update={"end": gene.start + served.AUDIT_MAX_WINDOW_BASES}
    )
    length = served.AUDIT_MAX_WINDOW_BASES + 1 + 2 * SELK_PAD

    with pytest.raises(ToolError, match=window_refused(GT1_SELK, length)):
        await audit_tools.audit_selenoprotein_end("toxodb", GT1_SELK, ME49_SELK)

    assert site.models_read == []
    assert site.windows == []


async def test_a_selenoprotein_window_at_the_limit_is_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = Site(monkeypatch)
    gene = gt1_selk_row()
    span = served.AUDIT_MAX_WINDOW_BASES - 2 * SELK_PAD
    site.rows[2] = gene.model_copy(update={"end": gene.start + span - 1})

    await served.selenoprotein_inputs("toxodb", GT1_SELK, ME49_SELK)

    [(_, _, start, end)] = site.windows
    assert end - start + 1 == served.AUDIT_MAX_WINDOW_BASES


@pytest.mark.parametrize(
    ("over", "gene", "pad"), [(0, NF54_PIGA_ID, 3000), (1, PIGA, 0)]
)
async def test_a_pseudogene_window_over_the_limit_is_a_tool_error(
    monkeypatch: pytest.MonkeyPatch, over: int, gene: str, pad: int
) -> None:
    site = Site(monkeypatch)
    reference = reference_piga_row()
    site.rows[1] = reference.model_copy(update={"end": reference.start + 99})
    row = site.rows[over]
    site.rows[over] = row.model_copy(
        update={"end": row.start + served.AUDIT_MAX_WINDOW_BASES}
    )
    length = served.AUDIT_MAX_WINDOW_BASES + 1 + 2 * pad

    with pytest.raises(ToolError, match=window_refused(gene, length)):
        await audit_tools.audit_pseudogene_call("plasmodb", NF54_PIGA, PIGA)

    assert pad == 0 or 100 * length <= served.PSEUDOGENE_MAX_CELLS
    assert site.models_read == []
    assert site.windows == []

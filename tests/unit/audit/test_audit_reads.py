from collections.abc import Coroutine

import pytest
from fastmcp.exceptions import ToolError
from pydantic import ValidationError
from tests._support.audit_fixtures import GT1_SELK, ME49_SELK, NF54_PIGA_ID, PIGA
from tests._support.audit_site import own_id
from tests._support.piga_selk_site import Site, reference_piga_row, strain_piga_row
from tests._support.proteins import row
from tests._support.site_failures import (
    SERVICE,
    answering,
    jbrowse_read,
    silent,
    wdk_read,
)
from veupathdb.errors import DataParsingError

from veupathdb_mcp.audit import served
from veupathdb_mcp.audit.served import (
    GeneLengthAudit,
    PseudogeneCallAudit,
    PseudogenePair,
    SelenoproteinEndAudit,
)
from veupathdb_mcp.tools import audit_tools
from veupathdb_mcp.tools.refusals import payload_or_error


@pytest.mark.parametrize(
    ("read", "named"),
    [
        (
            wdk_read(answering(404)),
            (
                "^plasmodb answered 404 to the audit reads: GET "
                "/record-types/transcript/searches/GenesByText -> HTTP 404: down$"
            ),
        ),
        (wdk_read(answering(503)), "^plasmodb answered 503 to the audit reads: "),
        (
            wdk_read(silent),
            "^plasmodb did not answer the audit reads: ConnectTimeout timed out$",
        ),
        (
            jbrowse_read(answering(503)),
            (
                "^plasmodb answered 503 to the audit reads: GET "
                f"{SERVICE}/jbrowse/rnaseqJunctions/pfal3D7 answered 503$"
            ),
        ),
        (
            jbrowse_read(silent),
            "^plasmodb did not answer the audit reads: ConnectTimeout timed out$",
        ),
    ],
)
async def test_a_site_failure_names_the_site_and_its_status_or_its_silence(
    read: Coroutine[None, None, None], named: str
) -> None:
    with pytest.raises(ToolError, match=named):
        await audit_tools.read_inputs("plasmodb", read)


async def test_a_refusal_that_is_no_site_failure_keeps_its_detail() -> None:
    async def truncated() -> None:
        msg = "WDK GeneByLocusTag report served 1 records of a total of 2"
        raise DataParsingError(msg)

    with pytest.raises(ToolError, match=r"^WDK GeneByLocusTag report served 1 "):
        await audit_tools.read_inputs("plasmodb", truncated())


@pytest.mark.parametrize(
    ("flag", "named"), [(False, "is_pseudo: No"), (None, "is_pseudo: not served")]
)
async def test_a_strain_gene_the_site_does_not_flag_as_a_pseudogene_is_refused(
    monkeypatch: pytest.MonkeyPatch, flag: bool | None, named: str
) -> None:
    site = Site(monkeypatch)
    site.rows[0] = strain_piga_row().model_copy(update={"pseudo": flag})

    with pytest.raises(
        ToolError,
        match=f"^{NF54_PIGA_ID} is not flagged a pseudogene on plasmodb \\({named}\\)",
    ):
        await audit_tools.audit_pseudogene_call("plasmodb", NF54_PIGA_ID, PIGA)

    assert (site.models_read, site.organisms_read, site.windows) == ([], [], [])


async def test_a_coding_reference_gene_given_as_the_strain_gene_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = Site(monkeypatch)

    with pytest.raises(ToolError, match=f"^{PIGA} is not flagged a pseudogene"):
        await audit_tools.audit_pseudogene_call("plasmodb", PIGA, PIGA)

    assert site.windows == []


async def test_the_pseudogene_check_reads_the_strain_organism_and_one_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = Site(monkeypatch)

    result = await audit_tools.audit_pseudogene_call("plasmodb", NF54_PIGA_ID, PIGA)

    assert result.verdict == "INTACT"
    assert (site.models_read, site.organisms_read) == ([PIGA], [NF54_PIGA_ID])


async def test_a_selenoprotein_id_resolved_by_alias_reads_its_protein_after(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = Site(monkeypatch)
    site.aliases = {"tggt1_316600": [GT1_SELK]}

    result = await audit_tools.audit_selenoprotein_end(
        "toxodb", "tggt1_316600", ME49_SELK
    )

    assert (result.verdict, result.gene) == ("STOPS_AT_SEC", GT1_SELK)
    assert [(i.given, i.resolved) for i in result.gene_ids] == [
        ("tggt1_316600", GT1_SELK),
        (ME49_SELK, ME49_SELK),
    ]
    assert site.proteins_read == [GT1_SELK, ME49_SELK]
    assert site.texts_read == ["tggt1_316600"]


async def test_served_answers_whose_gene_ids_name_other_genes_are_invalid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    Site(monkeypatch)
    call = await audit_tools.audit_pseudogene_call("plasmodb", NF54_PIGA_ID, PIGA)
    end = await audit_tools.audit_selenoprotein_end("toxodb", GT1_SELK, ME49_SELK)

    with pytest.raises(ValidationError, match="geneIds resolve to"):
        PseudogeneCallAudit.model_validate({**call.model_dump(), "strain_gene": PIGA})
    with pytest.raises(ValidationError, match="geneIds resolve to"):
        SelenoproteinEndAudit.model_validate({**end.model_dump(), "gene": ME49_SELK})
    with pytest.raises(ValidationError, match="geneIds resolve to"):
        GeneLengthAudit.model_validate(
            {**_unjudged_length(), "gene_ids": [own_id("OTHER")]}
        )


def _unjudged_length() -> dict[str, object]:
    return {
        "verdict": "NOT_CHECKED",
        "windows": 0,
        "counts": {},
        "track": "",
        "ns_in_window": None,
        "at_contig_edge": None,
        "gene_ids": [own_id("G")],
        "genes": ["G"],
        "length_class": "UNQUALIFIED",
        "ratio": None,
        "group_median": 400.0,
        "group_copies": 1.0,
        "group_spread": 0.0,
        "organisms": 3,
        "reference_gene": None,
        "code": None,
        "code_inferred": False,
    }


def test_an_unjudged_length_answer_with_its_own_ids_is_valid() -> None:
    assert GeneLengthAudit.model_validate(_unjudged_length()).genes == ["G"]


def test_a_pseudogene_pair_needs_a_flagged_strain_and_its_ids() -> None:
    strain, reference = strain_piga_row(), reference_piga_row()
    ids = [own_id(strain.gene), own_id(reference.gene)]

    assert PseudogenePair(strain=strain, reference=reference, gene_ids=ids)
    with pytest.raises(ValidationError, match="not flagged a pseudogene"):
        PseudogenePair(
            strain=strain.model_copy(update={"pseudo": False}),
            reference=reference,
            gene_ids=ids,
        )
    with pytest.raises(ValidationError, match="geneIds resolve to"):
        PseudogenePair(strain=strain, reference=reference, gene_ids=ids[::-1])


async def test_an_id_whose_record_read_names_two_genes_is_refused_naming_both(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = Site(monkeypatch)
    site.rows += [row("A1", "P f", 400), row("A2", "P f", 400)]
    site.echoes = {"OLD_A": ["A1", "A2"]}

    with pytest.raises(
        ToolError,
        match=r"^OLD_A names several genes of plasmodb: OLD_A maps to 2 records$",
    ):
        payload_or_error(await served.located("plasmodb", ["OLD_A"]))

    assert site.texts_read == []


async def test_every_id_no_read_names_is_named_in_one_refusal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = Site(monkeypatch)

    with pytest.raises(ToolError, match=r"^X1, X2 names no gene of plasmodb$"):
        payload_or_error(await served.located("plasmodb", ["X1", "X2"]))

    assert site.texts_read == ["X1", "X2"]

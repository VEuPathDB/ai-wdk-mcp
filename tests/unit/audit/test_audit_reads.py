from collections.abc import Coroutine

import httpx
import pytest
from fastmcp.exceptions import ToolError
from pydantic import ValidationError
from tests._support.audit_fixtures import GT1_SELK, ME49_SELK, NF54_PIGA_ID, PIGA
from tests._support.audit_site import own_id
from tests._support.piga_selk_site import Site, reference_piga_row, strain_piga_row
from tests._support.proteins import row
from tests._support.site_failures import (
    answering,
    jbrowse_read,
    silent,
    wdk_read,
)
from veupathdb.errors import DataParsingError, WDKError, validate_response
from veupathdb.jbrowse import GenomeIndexError, JBrowseError, TrackReadError
from veupathdb.wdk import WDKSearchResponse

from veupathdb_mcp.audit import served
from veupathdb_mcp.audit.served import (
    GeneLengthAudit,
    PseudogeneCallAudit,
    PseudogenePair,
    SelenoproteinEndAudit,
)
from veupathdb_mcp.audit.track_reads import failed_read
from veupathdb_mcp.parse_failures import WrittenParseError
from veupathdb_mcp.tools import audit_tools
from veupathdb_mcp.tools.refusals import payload_or_error


@pytest.mark.parametrize(
    ("read", "named"),
    [
        (wdk_read(answering(404)), "^plasmodb answered 404 to the audit reads$"),
        (wdk_read(answering(503)), "^plasmodb answered 503 to the audit reads$"),
        (wdk_read(silent), "^plasmodb did not answer the audit reads$"),
        (jbrowse_read(answering(503)), "^plasmodb answered 503 to the audit reads$"),
        (jbrowse_read(silent), "^plasmodb did not answer the audit reads$"),
    ],
)
async def test_a_site_failure_names_the_site_and_its_status_or_its_silence(
    read: Coroutine[None, None, None], named: str
) -> None:
    with pytest.raises(ToolError, match=named):
        await audit_tools.read_inputs("plasmodb", read)


SECRET_URL = "https://qa.plasmodb.org/plasmo.qa/service/x?api_key=SECRET"


def status_error() -> httpx.HTTPStatusError:
    request = httpx.Request("GET", SECRET_URL)
    response = httpx.Response(404, request=request, text="body with SECRET")
    return httpx.HTTPStatusError(
        f"Client error '404' for url '{SECRET_URL}'", request=request, response=response
    )


def wrapped(exc: Exception, cause: Exception) -> Exception:
    exc.__cause__ = cause
    return exc


def carried_errors() -> list[tuple[Exception, Exception, str]]:
    status = status_error()
    timeout = httpx.ConnectTimeout(f"timed out at {SECRET_URL}")
    answered = "plasmodb answered 404 to the audit reads"
    silent_site = "plasmodb did not answer the audit reads"
    return [
        (status, status, answered),
        (timeout, timeout, silent_site),
        (
            wrapped(WDKError(f"GET {SECRET_URL} -> 404: SECRET", status=404), status),
            status,
            answered,
        ),
        (
            wrapped(WDKError(f"Request failed: {SECRET_URL}"), timeout),
            timeout,
            silent_site,
        ),
        (JBrowseError("GET", SECRET_URL, 404), status, answered),
        (
            WDKError(f"Request failed after retries: {SECRET_URL}", status=404),
            status,
            answered,
        ),
    ]


@pytest.mark.parametrize("case", range(6))
async def test_a_site_failure_holds_no_upstream_text_and_keeps_its_cause(
    case: int,
) -> None:
    error, _, words = carried_errors()[case]

    async def read() -> None:
        raise error

    with pytest.raises(ToolError) as caught:
        await audit_tools.read_inputs("plasmodb", read())

    assert str(caught.value) == words
    assert caught.value.__cause__ is error
    assert "SECRET" not in str(caught.value)


@pytest.mark.parametrize(
    ("error", "words"),
    [
        (status_error(), "the header read failed: the site answered 404"),
        (
            JBrowseError("GET", SECRET_URL, 503),
            "the header read failed: the site answered 503",
        ),
        (
            httpx.ConnectTimeout(f"at {SECRET_URL}"),
            "the header read failed: the site did not answer",
        ),
        (
            wrapped(WDKError(f"GET {SECRET_URL}: SECRET", status=500), status_error()),
            "the header read failed: the site answered 404",
        ),
        (
            wrapped(
                WDKError(f"Request failed: {SECRET_URL}"), httpx.ConnectTimeout("x")
            ),
            "the header read failed: the site did not answer",
        ),
        (
            WDKError(f"GET {SECRET_URL}: SECRET", status=500),
            "the header read failed: the site answered 500",
        ),
    ],
)
def test_a_failed_track_read_holds_no_upstream_text(
    error: Exception, words: str
) -> None:
    assert failed_read("header read", error) == words


def test_a_computed_read_failure_keeps_its_words() -> None:
    error = TrackReadError("the index of f.bw names no such sequence")

    assert failed_read("depth read", error) == (
        "the depth read failed: the index of f.bw names no such sequence"
    )


def unreadable_answer() -> DataParsingError:
    try:
        validate_response(
            WDKSearchResponse,
            {"body": "<html>Tomcat SECRET stack</html>"},
            "search details",
        )
    except DataParsingError as exc:
        return exc
    raise AssertionError


async def test_an_answer_that_cannot_be_parsed_holds_no_upstream_text() -> None:
    error = unreadable_answer()

    async def read() -> None:
        raise error

    with pytest.raises(ToolError) as caught:
        await audit_tools.read_inputs("plasmodb", read())

    assert str(caught.value) == "the site's answer could not be read"
    assert caught.value.__cause__ is error
    assert "SECRET" in error.detail


def test_a_failed_read_that_cannot_be_parsed_holds_no_upstream_text() -> None:
    assert failed_read("header read", unreadable_answer()) == (
        "the header read failed: the site's answer could not be read"
    )


@pytest.mark.parametrize(
    "error",
    [
        DataParsingError("WDK GeneByLocusTag report served 1 records of a total of 2"),
        GenomeIndexError("the genome index of pfal3D7 has no sequence Pf3D7_10_v3"),
        TrackReadError("the index of f.bw names no such sequence"),
    ],
)
async def test_a_read_failure_keeps_its_words_and_stays_chained(
    error: Exception,
) -> None:
    async def read() -> None:
        raise error

    with pytest.raises(ToolError) as caught:
        await audit_tools.read_inputs("plasmodb", read())

    assert str(caught.value) == str(error.detail)
    assert caught.value.__cause__ is error


async def test_a_written_parse_failure_keeps_its_words_and_stays_chained() -> None:
    async def read() -> None:
        try:
            WDKSearchResponse.model_validate({})
        except ValidationError as exc:
            msg = "the gene record of G on plasmodb gives no organismAbbrev"
            raise WrittenParseError(msg) from exc

    with pytest.raises(ToolError) as caught:
        await audit_tools.read_inputs("plasmodb", read())

    assert (
        str(caught.value) == "the gene record of G on plasmodb gives no organismAbbrev"
    )
    assert isinstance(caught.value.__cause__, WrittenParseError)


async def test_a_parse_failure_nobody_wrote_reads_unreadable_whatever_its_detail() -> (
    None
):
    async def read() -> None:
        try:
            WDKSearchResponse.model_validate({})
        except ValidationError as exc:
            msg = "words that do not hold the validation text"
            raise DataParsingError(msg) from exc

    with pytest.raises(ToolError) as caught:
        await audit_tools.read_inputs("plasmodb", read())

    assert str(caught.value) == "the site's answer could not be read"


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
        match=r"^OLD_A names several genes of plasmodb$",
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

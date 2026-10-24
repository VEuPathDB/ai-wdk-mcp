import json

import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError
from scripts.record_audit_gene_ids import FILE, GeneIdRecording
from tests._support.dataset_trap import DatasetTrap
from tests._support.record_site import install_recorded_records, load_records
from tests._support.wdk_genes import (
    FIXTURES,
    answer_of,
    gene_attributes,
    record,
)
from veupathdb.auth_context import veupathdb_auth_token_ctx
from veupathdb.errors import VEuPathDBErrorCode, WDKError
from veupathdb.wdk import (
    WDKAnswer,
    WDKRecordInstance,
    WDKSearchConfig,
    WDKSearchResponse,
)

from veupathdb_mcp.audit import gene_ids, gene_models, record_reads, served
from veupathdb_mcp.audit.gene_ids import GeneReads, rows_named
from veupathdb_mcp.audit.genes import GeneRow
from veupathdb_mcp.audit.record_reads import (
    MAX_LIST_IDS,
    RECORD_ATTRIBUTES,
    RECORD_READS_PER_CALL,
    read_gene_list,
    record_proteins,
    record_rows,
)
from veupathdb_mcp.tool_errors import tool_error
from veupathdb_mcp.tools.refusals import payload_or_error
from veupathdb_mcp.wdk.site_cache import SiteCache

PIGA = "PF3D7_1032400"
PIGA_RECORDS = "records_pfal3D7_piga.json"
PIGA_ROW = GeneRow(
    gene=PIGA,
    organism="Plasmodium falciparum 3D7",
    ortholog_group="OG8_0001100",
    protein_length=461,
    name="PIGA",
    product="phosphatidylinositol N-acetylglucosaminyltransferase subunit A, putative",
    sequence_id="Pf3D7_10_v3",
    start=1302298,
    end=1305315,
    strand="-",
    pseudo=False,
    gene_type="protein coding gene",
)


def test_the_recording_holds_the_reads_by_id_and_the_transcript_id_refused() -> None:
    wire = load_records(PIGA_RECORDS)

    assert wire.transcript_key == ["gene_source_id", "source_id", "project_id"]
    assert [
        (r.record_type, r.primary_key["source_id"], r.status) for r in wire.records
    ] == [
        ("gene", PIGA, 200),
        ("gene", PIGA, 200),
        ("transcript", f"{PIGA}.1", 200),
        ("gene", PIGA, 200),
        ("gene", "PF10_0316", 200),
        ("gene", "CZT98581.1", 200),
        ("gene", f"{PIGA}.1", 404),
    ]


async def test_a_named_gene_is_one_gene_record_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = install_recorded_records(monkeypatch, load_records(PIGA_RECORDS))

    assert await record_rows("plasmodb", [PIGA]) == [PIGA_ROW]
    assert records.reads == [("gene", PIGA, ("GeneTranscripts",))]


async def test_a_protein_is_read_from_the_longest_transcript_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = install_recorded_records(monkeypatch, load_records(PIGA_RECORDS))

    proteins = await record_proteins("plasmodb", [PIGA])

    assert len(proteins[PIGA]) == 461
    assert proteins[PIGA].startswith("MESAVSECNIYKKE")
    assert records.reads == [
        ("gene", PIGA, ("GeneTranscripts",)),
        ("transcript", f"{PIGA}.1", ()),
    ]


class Transcripts:
    def __init__(self) -> None:
        self.reads: list[tuple[str, str]] = []

    async def get_single_record(
        self,
        record_type: str,
        primary_key: list[dict[str, str]],
        *,
        attributes: list[str] | None = None,
        tables: list[str] | None = None,
    ) -> WDKRecordInstance:
        key = {part["name"]: part["value"] for part in primary_key}
        self.reads.append((record_type, key["source_id"]))
        if record_type == "gene":
            return WDKRecordInstance.model_validate(
                {
                    "id": [{"name": "source_id", "value": "EXA_0001"}],
                    "attributes": {},
                    "tables": {
                        "GeneTranscripts": [
                            {"transcript_id": "EXA_0001-t1", "protein_length": "120"},
                            {"transcript_id": "EXA_0001-t2", "protein_length": "300"},
                            {"transcript_id": "EXA_0001-t3", "protein_length": ""},
                        ]
                    },
                }
            )
        return WDKRecordInstance.model_validate(
            {
                "id": [{"name": "source_id", "value": key["source_id"]}],
                "attributes": {"protein_sequence": "M" * 300 + "*"},
                "tables": {},
            }
        )


async def test_the_longest_of_several_transcripts_is_the_only_one_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = Transcripts()
    monkeypatch.setattr(gene_models, "get_strategy_api", lambda s: site)
    monkeypatch.setattr(record_reads, "get_strategy_api", lambda s: site)

    proteins = await record_proteins("plasmodb", ["EXA_0001"])

    assert proteins == {"EXA_0001": "M" * 300}
    assert site.reads == [("gene", "EXA_0001"), ("transcript", "EXA_0001-t2")]


@pytest.mark.parametrize("read", [record_rows, record_proteins, rows_named])
async def test_more_named_genes_than_the_bound_are_refused_before_a_read(
    monkeypatch: pytest.MonkeyPatch, read
) -> None:
    records = install_recorded_records(monkeypatch, load_records(PIGA_RECORDS))
    named = [f"EXA_{n:04}" for n in range(RECORD_READS_PER_CALL + 1)]

    with pytest.raises(
        ToolError, match="81 genes are named; record reads read at most 80"
    ):
        await read("plasmodb", named)
    assert records.reads == []


class TextSite:
    def __init__(self, search: WDKSearchResponse, text: WDKAnswer) -> None:
        self.search = search
        self.text = text
        self.reads: list[str] = []

    async def get_search_details(
        self, record_type: str, search_name: str
    ) -> WDKSearchResponse:
        self.reads.append(f"details:{search_name}")
        return self.search

    async def run_search_report(
        self,
        record_type: str,
        search_name: str,
        search_config: WDKSearchConfig,
        report_config: object = None,
    ) -> WDKAnswer:
        self.reads.append(
            f"{search_name}:{search_config.parameters['text_expression']}"
        )
        return self.text


def text_site(monkeypatch: pytest.MonkeyPatch, text: WDKAnswer) -> TextSite:
    wire = GeneIdRecording.model_validate_json((FIXTURES / FILE).read_text())
    site = TextSite(WDKSearchResponse.model_validate(wire.search), text)
    monkeypatch.setattr(gene_ids, "get_wdk_client", lambda site_id: site)
    monkeypatch.setattr(gene_ids, "_ORGANISMS", SiteCache())
    return site


@pytest.mark.parametrize("given", ["PF10_0316", "CZT98581.1"])
async def test_a_previous_or_alternate_id_resolves_in_its_own_record_read(
    monkeypatch: pytest.MonkeyPatch, given: str
) -> None:
    records = install_recorded_records(monkeypatch, load_records(PIGA_RECORDS))
    text = text_site(monkeypatch, answer_of([]))

    rows = payload_or_error(await served.located("plasmodb", [given]))

    assert rows == {given: PIGA_ROW}
    assert records.reads == [("gene", given, ("GeneTranscripts",))]
    assert text.reads == []


async def test_a_transcript_id_resolves_by_text_then_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = install_recorded_records(monkeypatch, load_records(PIGA_RECORDS))
    hit = record(PIGA, f"{PIGA}.1", gene_attributes("461", "No", "protein coding gene"))
    text = text_site(monkeypatch, answer_of([hit]))

    reads = await rows_named("plasmodb", [f"{PIGA}.1"])

    assert reads == GeneReads(
        rows=[PIGA_ROW], proteins={}, inputs={f"{PIGA}.1".lower(): [PIGA]}
    )
    assert records.reads == [
        ("gene", f"{PIGA}.1", ("GeneTranscripts",)),
        ("gene", PIGA, ("GeneTranscripts",)),
    ]
    assert text.reads == ["details:GenesByText", f"GenesByText:{PIGA}.1"]


def _recorded_body(request: httpx.Request) -> httpx.Response:
    if request.url.path.endswith("/app"):
        return httpx.Response(200, text="ok")
    if request.url.path.endswith("/users/current"):
        return httpx.Response(200, json={"id": 42, "isGuest": False})
    sent = json.loads(request.content)
    key = {part["name"]: part["value"] for part in sent["primaryKey"]}
    for exchange in load_records(PIGA_RECORDS).records:
        if (exchange.record_type, exchange.primary_key, exchange.attributes) == (
            "gene",
            key,
            sent["attributes"],
        ):
            return httpx.Response(exchange.status, json=exchange.body)
    return httpx.Response(500, text="not recorded")


@respx.mock
async def test_a_list_read_posts_no_dataset_and_reads_each_gene_record() -> None:
    route = respx.route().mock(side_effect=_recorded_body)
    reset = veupathdb_auth_token_ctx.set("researcher.registered.token")
    try:
        rows = await read_gene_list("plasmodb", [PIGA])
    finally:
        veupathdb_auth_token_ctx.reset(reset)

    assert rows == [PIGA_ROW]
    assert [(call.request.method, call.request.url.path) for call in route.calls] == [
        ("GET", "/plasmo.qa/app"),
        ("GET", "/plasmo.qa/service/users/current"),
        ("POST", "/plasmo.qa/service/record-types/gene/records"),
    ]
    assert [json.loads(call.request.content) for call in route.calls[2:]] == [
        {
            "primaryKey": [
                {"name": "source_id", "value": PIGA},
                {"name": "project_id", "value": "PlasmoDB"},
            ],
            "attributes": list(RECORD_ATTRIBUTES),
            "tables": ["GeneTranscripts"],
        }
    ]


async def test_a_list_read_keeps_one_row_per_gene_and_drops_an_id_no_record_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = install_recorded_records(monkeypatch, load_records(PIGA_RECORDS))
    text = text_site(monkeypatch, answer_of([]))
    trap = DatasetTrap(monkeypatch)

    rows = await read_gene_list("plasmodb", [PIGA, "PF10_0316", f"{PIGA}.1"])

    assert rows == [PIGA_ROW]
    assert records.reads == [
        ("gene", PIGA, ("GeneTranscripts",)),
        ("gene", "PF10_0316", ("GeneTranscripts",)),
        ("gene", f"{PIGA}.1", ("GeneTranscripts",)),
    ]
    assert (text.reads, trap.calls) == ([], [])


async def test_a_list_past_its_bound_is_refused_before_a_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = install_recorded_records(monkeypatch, load_records(PIGA_RECORDS))

    with pytest.raises(ToolError, match="401 genes are named; one list read"):
        await read_gene_list("plasmodb", [f"EXA_{n:04}" for n in range(401)])
    assert (MAX_LIST_IDS, records.reads) == (400, [])


async def test_an_empty_list_reads_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    records = install_recorded_records(monkeypatch, load_records(PIGA_RECORDS))

    assert (await read_gene_list("plasmodb", []), records.reads) == ([], [])


async def test_an_id_that_maps_to_several_records_is_refused_by_the_site_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def several(site_id: str, gene: str) -> GeneRow:
        msg = "source_id = EXA_0001\nsource_id = EXA_0002"
        raise WDKError(msg, status=300)

    monkeypatch.setattr(record_reads, "_row", several)
    text = text_site(monkeypatch, answer_of([]))

    refusal = await rows_named("plasmodb", ["OLD_EXA"])

    assert refusal == tool_error(
        VEuPathDBErrorCode.VALIDATION_ERROR,
        "OLD_EXA names several genes of plasmodb: "
        "source_id = EXA_0001\nsource_id = EXA_0002",
    )
    assert text.reads == []

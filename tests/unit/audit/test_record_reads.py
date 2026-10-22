from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from fastmcp.exceptions import ToolError
from scripts.record_audit_gene_ids import FILE, GeneIdRecording
from tests._support.record_site import install_recorded_records, load_records
from tests._support.wdk_genes import (
    FIXTURES,
    Datasets,
    ReportSite,
    answer_of,
    gene_attributes,
    record,
)
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
    LIST_MAX_PAGES,
    LIST_PAGE_RECORDS,
    MAX_LIST_IDS,
    RECORD_READS_PER_CALL,
    one_list_rows,
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


def list_site(monkeypatch: pytest.MonkeyPatch, pages: list[WDKAnswer]) -> ReportSite:
    site = ReportSite(pages)

    @asynccontextmanager
    async def opened(site_id: str) -> AsyncIterator[ReportSite]:
        yield site

    monkeypatch.setattr(record_reads, "dataset_client", opened)
    monkeypatch.setattr(record_reads, "StrategyAPI", Datasets)
    return site


def transcripts(gene: str) -> list[dict[str, object]]:
    return [
        record(
            gene,
            f"{gene}-t{n}",
            gene_attributes(str(length), "No", "protein coding gene"),
        )
        for n, length in ((1, 300), (2, 420), (3, 280))
    ]


async def test_one_list_read_uploads_one_dataset_and_pages_its_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    named = [f"EXA_{n:04}" for n in range(MAX_LIST_IDS)]
    served = [r for gene in named for r in transcripts(gene)]
    site = list_site(
        monkeypatch,
        [
            answer_of(served[:LIST_PAGE_RECORDS], total=len(served)),
            answer_of(served[LIST_PAGE_RECORDS:], total=len(served)),
        ],
    )

    rows = await one_list_rows("plasmodb", named)

    assert sorted(row.gene for row in rows) == named
    assert {row.protein_length for row in rows} == {420}
    assert [d.source_content.ids for d in site.datasets] == [named]
    assert [report["pagination"] for *_, report in site.searches] == [
        {"offset": 0, "numRecords": LIST_PAGE_RECORDS},
        {"offset": LIST_PAGE_RECORDS, "numRecords": LIST_PAGE_RECORDS},
    ]


async def test_a_list_report_past_its_page_cap_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    named = [f"EXA_{n:04}" for n in range(MAX_LIST_IDS)]
    served = [r for gene in named for r in transcripts(gene)][:LIST_PAGE_RECORDS]
    total = LIST_MAX_PAGES * LIST_PAGE_RECORDS + 1
    site = list_site(
        monkeypatch, [answer_of(served, total=total) for _ in range(LIST_MAX_PAGES)]
    )

    with pytest.raises(
        ToolError, match=f"serves {total} transcripts; one list read pages at most 4000"
    ):
        await one_list_rows("plasmodb", named)
    assert (len(site.datasets), len(site.searches)) == (1, LIST_MAX_PAGES)


async def test_a_list_past_its_bound_is_refused_before_a_dataset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = list_site(monkeypatch, [])

    with pytest.raises(ToolError, match="401 genes are named; one list read"):
        await one_list_rows("plasmodb", [f"EXA_{n:04}" for n in range(401)])
    assert site.datasets == []


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

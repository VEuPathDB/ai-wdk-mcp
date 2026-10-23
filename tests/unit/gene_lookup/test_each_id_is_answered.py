import pytest
from fastmcp.exceptions import ToolError
from scripts.record_audit_gene_ids import BESIDE
from scripts.record_gene_lookups import RESOLVED
from tests._support.dataset_trap import DatasetTrap
from tests._support.record_site import install_recorded_records, load_records
from tests._support.record_types import (
    ORTHOMCL_RECORDING,
    RecordedRecordTypes,
    orthomcl_gene_read,
    orthomcl_wire,
    serve_record_types,
)
from tests._support.row_reads import RowReads, serve_recorded_rows
from tests.unit.audit import test_gene_ids
from tests.unit.gene_lookup import test_a_lookup_reads_by_record
from veupathdb.errors import WDKError
from veupathdb.testing import NEEDS_QA_RECORDING, needs_qa_recording

from veupathdb_mcp.audit import (
    RECORD_READS_PER_CALL,
    GeneIdProblem,
    GeneIdRefusal,
    TooManyIdsError,
    record_proteins,
    record_reads,
    record_rows,
)
from veupathdb_mcp.catalog import NoGeneRecordsError
from veupathdb_mcp.gene_lookup import (
    GeneIdFound,
    read_each_gene_id,
    read_gene_ids,
)
from veupathdb_mcp.gene_lookup.records import gene_result
from veupathdb_mcp.tools import user_tools

SITE = "plasmodb"
SEVERAL = "PF3D7_SEVERAL"
UNKNOWN = "PF10_0327"
PIGA_TRANSCRIPT = "PF3D7_1032400.1"

needs_orthomcl = pytest.mark.skipif(
    needs_qa_recording(ORTHOMCL_RECORDING), reason=NEEDS_QA_RECORDING
)


def several_genes(monkeypatch: pytest.MonkeyPatch, reads: RowReads) -> None:
    async def row(site_id: str, gene: str) -> object:
        if gene == SEVERAL:
            reads.reads.append(gene)
            msg = f"{gene} names 2 records"
            raise WDKError(msg, status=300)
        return await reads.row(site_id, gene)

    monkeypatch.setattr(record_reads, "_row", row)


def mixed(monkeypatch: pytest.MonkeyPatch) -> tuple[RowReads, test_gene_ids.TextSite]:
    held = test_gene_ids.recorded()
    _, text = test_gene_ids.serve(monkeypatch, [], test_gene_ids.answers(held.text))
    reads = serve_recorded_rows(monkeypatch, [*held.batch, *held.resolved])
    several_genes(monkeypatch, reads)
    return reads, text


async def test_each_id_of_a_mixed_list_has_its_own_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reads, text = mixed(monkeypatch)
    trap = DatasetTrap(monkeypatch)

    readings = await read_each_gene_id(SITE, [BESIDE, SEVERAL, UNKNOWN])

    assert readings == [
        GeneIdFound(given=BESIDE, records=[gene_result(reads.rows[BESIDE])]),
        GeneIdRefusal(
            given=SEVERAL,
            problem=GeneIdProblem.SEVERAL_GENES,
            message=f"{SEVERAL} names several genes of {SITE}: {SEVERAL} names 2 records",
        ),
        GeneIdRefusal(
            given=UNKNOWN,
            problem=GeneIdProblem.NOT_FOUND,
            message=f"{UNKNOWN} names no gene of {SITE}",
        ),
    ]
    assert reads.rows[BESIDE].organism == "Plasmodium falciparum 3D7"
    assert reads.reads == [BESIDE, SEVERAL, UNKNOWN]
    assert [search[2].parameters["text_expression"] for search in text.searches] == [
        UNKNOWN
    ]
    assert trap.calls == []


async def test_the_whole_list_read_stops_at_the_first_refused_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reads, text = mixed(monkeypatch)

    result = await read_gene_ids(SITE, [BESIDE, SEVERAL, UNKNOWN])

    assert (result.records, result.total_count) == ([], 0)
    assert result.error == (
        f"{SEVERAL} names several genes of {SITE}: {SEVERAL} names 2 records"
    )
    assert (reads.reads, text.searches) == ([BESIDE, SEVERAL], [])


async def test_the_whole_list_read_leaves_out_an_id_that_names_no_gene(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mixed(monkeypatch)

    result = await read_gene_ids(SITE, [BESIDE, UNKNOWN])

    assert ([r.gene_id for r in result.records], result.error) == ([BESIDE], None)


async def test_a_list_past_the_bound_is_refused_by_name_before_any_request(
    monkeypatch: pytest.MonkeyPatch, listed_record_types: RecordedRecordTypes
) -> None:
    reads, text = mixed(monkeypatch)
    named = [f"PF3D7_{index:07d}" for index in range(RECORD_READS_PER_CALL + 1)]

    with pytest.raises(TooManyIdsError) as refused:
        await read_each_gene_id(SITE, named)

    assert (refused.value.named, refused.value.bound) == (81, 80)
    assert str(refused.value) == (
        "81 genes are named; record reads read at most 80 at once"
    )
    assert (reads.reads, text.details, listed_record_types.asked) == ([], [], [])


async def test_a_list_that_resolves_asks_for_no_record_types(
    monkeypatch: pytest.MonkeyPatch, listed_record_types: RecordedRecordTypes
) -> None:
    records = test_a_lookup_reads_by_record.replay(monkeypatch)

    readings = await read_each_gene_id(SITE, RESOLVED)

    assert [reading.outcome for reading in readings] == ["found", "found"]
    assert [read[1] for read in records.reads] == RESOLVED
    assert (listed_record_types.asked, listed_record_types.catalog_asked) == ([], [])


async def test_a_missing_record_is_absent_where_the_site_lists_genes(
    monkeypatch: pytest.MonkeyPatch, listed_record_types: RecordedRecordTypes
) -> None:
    records = install_recorded_records(
        monkeypatch, load_records("records_pfal3D7_piga.json")
    )

    assert await record_reads.found_row(SITE, PIGA_TRANSCRIPT) is None
    assert await record_reads.found_row(SITE, PIGA_TRANSCRIPT) is None

    assert [read[1] for read in records.reads] == [PIGA_TRANSCRIPT, PIGA_TRANSCRIPT]
    assert (listed_record_types.asked, listed_record_types.catalog_asked) == (
        [SITE],
        [],
    )


async def test_a_held_catalog_answers_the_record_types(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    listed = serve_record_types(monkeypatch, held=[SITE])
    install_recorded_records(monkeypatch, load_records("records_pfal3D7_piga.json"))

    assert await record_reads.found_row(SITE, PIGA_TRANSCRIPT) is None

    assert (listed.asked, listed.catalog_asked) == ([], [SITE])


@needs_orthomcl
def test_the_orthomcl_recording_lists_no_gene_record_type() -> None:
    wire = orthomcl_wire()

    assert (wire.site, wire.record_types.status) == ("orthomcl", 200)
    assert wire.record_types.url == (
        "https://qa.orthomcl.org/orthomcl.qa/service/record-types"
    )
    assert "gene" not in [str(name) for name in wire.record_types.response_json]
    assert wire.gene_record.status == 404


@needs_orthomcl
async def test_a_site_that_lists_no_gene_record_type_is_refused_after_the_first_read(
    monkeypatch: pytest.MonkeyPatch, listed_record_types: RecordedRecordTypes
) -> None:
    records = install_recorded_records(monkeypatch, orthomcl_gene_read())
    gene = orthomcl_wire().gene

    with pytest.raises(NoGeneRecordsError) as refused:
        await read_each_gene_id("orthomcl", [gene, BESIDE])

    assert refused.value.site_id == "orthomcl"
    assert refused.value.detail == (
        "orthomcl lists no gene record type, so it reads no gene by id"
    )
    assert [read[1] for read in records.reads] == [gene]
    assert listed_record_types.asked == ["orthomcl"]


@needs_orthomcl
async def test_the_served_resolve_names_a_site_without_genes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_recorded_records(monkeypatch, orthomcl_gene_read())

    with pytest.raises(ToolError, match=r"^orthomcl lists no gene record type"):
        await user_tools.resolve_gene_ids_to_records("orthomcl", [orthomcl_wire().gene])


@needs_orthomcl
async def test_the_audit_record_reads_refuse_a_site_without_genes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_recorded_records(monkeypatch, orthomcl_gene_read())
    gene = orthomcl_wire().gene

    with pytest.raises(NoGeneRecordsError):
        await record_rows("orthomcl", [gene])
    with pytest.raises(NoGeneRecordsError):
        await record_proteins("orthomcl", [gene])
    with pytest.raises(NoGeneRecordsError):
        await record_reads.found_row("orthomcl", gene)

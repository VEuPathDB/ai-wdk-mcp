from collections.abc import Iterator

import pytest
from fastmcp.exceptions import ToolError
from scripts.record_audit_records import RecordWire
from scripts.record_gene_lookups import (
    FILE,
    FIXTURES,
    HYDRATED,
    RESOLVED,
    SITE,
    LookupWire,
)
from tests._support.dataset_trap import DatasetTrap
from tests._support.record_site import (
    RECORD_ROW,
    RecordedRecords,
    install_recorded_records,
)
from tests._support.row_reads import serve_recorded_rows
from tests.unit.audit import test_gene_ids
from veupathdb.auth_context import veupathdb_auth_token_ctx
from veupathdb.errors import WDKError

from veupathdb_mcp.audit import (
    RECORD_READS_PER_CALL,
    GeneIdProblem,
    GeneIdRefusal,
    gene_ids,
    record_reads,
)
from veupathdb_mcp.audit.genes import GeneRow
from veupathdb_mcp.gene_lookup import GeneResult, lookup
from veupathdb_mcp.tools import user_tools


def wire() -> LookupWire:
    return LookupWire.model_validate_json((FIXTURES / FILE).read_text())


def replay(monkeypatch: pytest.MonkeyPatch) -> RecordedRecords:
    held = wire()
    return install_recorded_records(
        monkeypatch, RecordWire(site=held.site, transcript_key=[], records=held.records)
    )


def test_the_wire_holds_record_reads_alone() -> None:
    held = wire()

    assert (held.site, held.resolved, held.hydrated) == (SITE, RESOLVED, HYDRATED)
    assert [
        (r.record_type, r.primary_key["source_id"], r.status) for r in held.records
    ] == [("gene", gene, 200) for gene in [*RESOLVED, *HYDRATED]]


async def test_a_resolve_reads_each_named_gene_by_its_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = replay(monkeypatch)
    trap = DatasetTrap(monkeypatch)

    result = await user_tools.resolve_gene_ids_to_records(SITE, RESOLVED)

    assert [r.gene_id for r in result.records] == ["PF3D7_1133400", "PF3D7_1032400"]
    assert (result.total_count, result.error) == (2, None)
    assert {r.organism for r in result.records} == {"Plasmodium falciparum 3D7"}
    assert [r.location for r in result.records] == [
        "Pf3D7_11_v3:1,292,966..1,296,696(+)",
        "Pf3D7_10_v3:1,302,298..1,305,315(-)",
    ]
    assert [r.previous_ids for r in result.records] == ["", ""]
    assert [read[1] for read in records.reads] == RESOLVED
    assert trap.calls == []


async def test_a_lookup_fills_a_sparse_gene_from_its_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = replay(monkeypatch)
    [gene] = HYDRATED

    async def page(
        site_id: str, search_text: str, **_: object
    ) -> tuple[list[GeneResult], list[str], int]:
        return [GeneResult(gene_id=gene)], [], 1

    monkeypatch.setattr(lookup, "fetch_site_search_genes", page)
    trap = DatasetTrap(monkeypatch)

    result = await user_tools.lookup_gene_records(SITE, gene)

    [found] = result.records
    assert (found.gene_id, found.organism) == (gene, "Plasmodium falciparum 3D7")
    assert found.product == "AP2 domain transcription factor AP2-G"
    assert [read[1] for read in records.reads] == HYDRATED
    assert trap.calls == []


async def test_one_ambiguous_hit_leaves_the_other_hits_filled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    replay(monkeypatch)
    [gene] = HYDRATED
    ambiguous = "PF3D7_AMBIGUOUS"

    async def row(site_id: str, named: str) -> GeneRow:
        if named == ambiguous:
            msg = f"{named} names 2 records"
            raise WDKError(msg, status=300)
        return await RECORD_ROW(site_id, named)

    async def page(
        site_id: str, search_text: str, **_: object
    ) -> tuple[list[GeneResult], list[str], int]:
        return [GeneResult(gene_id=ambiguous), GeneResult(gene_id=gene)], [], 2

    monkeypatch.setattr(record_reads, "_row", row)
    monkeypatch.setattr(lookup, "fetch_site_search_genes", page)

    result = await user_tools.lookup_gene_records(SITE, gene)

    filled = {r.gene_id: (r.organism, r.product) for r in result.records}
    assert filled == {
        ambiguous: ("", ""),
        gene: ("Plasmodium falciparum 3D7", "AP2 domain transcription factor AP2-G"),
    }


async def test_an_id_no_record_names_resolves_through_the_text_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    held = test_gene_ids.recorded()
    test_gene_ids.serve(monkeypatch, [], test_gene_ids.answers(held.text))
    reads = serve_recorded_rows(monkeypatch, [*held.batch, *held.resolved])

    result = await user_tools.resolve_gene_ids_to_records(SITE, [held.given])

    assert [r.gene_id for r in result.records] == [test_gene_ids.RESOLVED]
    assert reads.reads == [held.given, test_gene_ids.RESOLVED]


async def test_an_id_several_genes_answer_is_an_error_with_no_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def refused(site_id: str, gene_id: str) -> object:
        return GeneIdRefusal(
            given=gene_id,
            problem=GeneIdProblem.SEVERAL_GENES,
            message=f"{gene_id} names 2",
        )

    monkeypatch.setattr(gene_ids, "_named", refused)

    result = await user_tools.resolve_gene_ids_to_records(SITE, ["PF3D7_1"])

    assert (result.records, result.total_count, result.error) == (
        [],
        0,
        "PF3D7_1 names 2",
    )


async def test_a_resolve_past_the_record_reads_of_one_call_is_refused() -> None:
    named = [f"PF3D7_{index:07d}" for index in range(RECORD_READS_PER_CALL + 1)]

    with pytest.raises(ToolError, match="gene_ids holds 81 identifiers"):
        await user_tools.resolve_gene_ids_to_records(SITE, named)


@pytest.fixture(autouse=True)
def researcher() -> Iterator[None]:
    reset = veupathdb_auth_token_ctx.set("researcher.registered.token")
    yield
    veupathdb_auth_token_ctx.reset(reset)

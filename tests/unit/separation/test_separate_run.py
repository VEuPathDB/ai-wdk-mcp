"""One run end to end: resolve, clean up, upload, collect, measure, assemble, confirm."""

from datetime import timedelta

import pytest
from pydantic import ValidationError
from tests._support.control_run_wdk import RunFakeAPI, wdk_time
from tests._support.recorded_searches import gene_list_search, recorded_search
from tests._support.separation_site import FALCIPARUM, patch_site
from veupathdb.domain.parameters import MultiPickValue, StringValue
from veupathdb.errors import WDKError
from veupathdb.testing import NEEDS_QA_RECORDING, needs_qa_recording
from veupathdb.testing.wdk_fixtures import load_recorded
from veupathdb.wdk import (
    VEuPathDBClient,
    WDKStrategySummary,
    tag_internal_wdk_strategy_name,
)

from veupathdb_mcp.gene_lookup import GeneResolveResult, GeneResult
from veupathdb_mcp.separation import (
    CLEANUP_REQUESTS,
    CONFIRM_RESERVATION,
    ENRICHMENT_REQUESTS,
    FIRST_INTERSECTION_REQUESTS,
    MAX_CRITERIA,
    MEASURE_REQUESTS,
    RESOLVE_REQUESTS,
    SEARCH_READ_REQUESTS,
    UPLOAD_REQUESTS,
    SeparationRequest,
    SeparationUpdate,
    ThreadSearch,
    TooFewControls,
    confirm_requests,
    separate,
)
from veupathdb_mcp.separation import run as separation_run
from veupathdb_mcp.wdk.enrichment import BackgroundSource, GeneIdEnrichment

NAME = "control separation"
POSITIVES = [f"PF3D7_01001{i}0" for i in range(5)]
NEGATIVES = [f"PF3D7_02001{i}0" for i in range(5)]
UNKNOWN = "PF3D7_9999999"
UNHELD = [f"PF3D7_99001{i}0" for i in range(5)]
# Two resolutions, the cleanup and its one delete, the upload, the enrichment,
# three search reads (the weight search, its catalog binding, the locus-tag
# search), one first measurement, and the confirm read of one leaf.
CHARGED = (
    2 * RESOLVE_REQUESTS
    + CLEANUP_REQUESTS
    + 1
    + UPLOAD_REQUESTS
    + ENRICHMENT_REQUESTS
    + 3 * SEARCH_READ_REQUESTS
    + MEASURE_REQUESTS
    + SEARCH_READ_REQUESTS
    + FIRST_INTERSECTION_REQUESTS
    + confirm_requests(1)
)
WEIGHT = ThreadSearch(
    search_name="GenesByMolecularWeight",
    parameters={
        "organism": MultiPickValue(values=[FALCIPARUM]),
        "min_molecular_weight": StringValue(value="10000"),
        "max_molecular_weight": StringValue(value="50000"),
    },
)


class _Account(RunFakeAPI):
    """An account that holds one leftover of an interrupted run."""

    async def list_strategies(self) -> list[WDKStrategySummary]:
        self.calls.append("list_strategies")
        return [
            WDKStrategySummary(
                strategy_id=77,
                name=tag_internal_wdk_strategy_name(NAME),
                root_step_id=1,
                created_time=wdk_time(timedelta(days=3)),
            )
        ]


@pytest.fixture
def account(monkeypatch: pytest.MonkeyPatch) -> _Account:
    api = _Account(step_count=5012, answer_ids=(*POSITIVES, "PF3D7_0300100"))
    monkeypatch.setattr(separation_run, "get_strategy_api", lambda site_id: api)

    async def resolve(site_id: str, gene_ids: list[str]) -> GeneResolveResult:
        records = [
            GeneResult(gene_id=gene_id, organism=FALCIPARUM, product="rhoptry protein")
            for gene_id in gene_ids
            if gene_id != UNKNOWN and gene_id not in UNHELD
        ]
        return GeneResolveResult(records=records, total_count=len(records))

    monkeypatch.setattr(separation_run, "resolve_gene_ids", resolve)
    patch_site(
        monkeypatch,
        [
            recorded_search("search_genes_by_molecular_weight"),
            recorded_search("search_genes_by_orthologs"),
            gene_list_search(),
        ],
        enrichment=GeneIdEnrichment(
            site_id="plasmodb",
            gene_count=3,
            background=BackgroundSource(organism=FALCIPARUM),
            analyses=[],
        ),
    )
    return api


def _request(**kwargs) -> SeparationRequest:
    fields = {
        "positives": POSITIVES,
        "negatives": [*NEGATIVES, UNKNOWN],
        "mode": "exact",
        "thread": [WEIGHT],
        "budget": 400,
    } | kwargs
    return SeparationRequest.model_validate(fields)


async def _run(request: SeparationRequest) -> tuple:
    rows: list[SeparationUpdate] = []

    async def progress(update: SeparationUpdate) -> None:
        rows.append(update)

    result = await separate("plasmodb", request, strategy_name=NAME, progress=progress)
    return result, rows


@pytest.mark.skipif(
    needs_qa_recording(
        "wdk/search_genes_by_molecular_weight.json",
        "wdk/search_genes_by_orthologs.json",
    ),
    reason=NEEDS_QA_RECORDING,
)
async def test_the_thread_search_separates_and_the_read_confirms_it(
    account: _Account,
) -> None:
    result, _ = await _run(_request())

    assert result.separates is True
    assert result.tree is not None
    assert (result.tree.kind, result.tree.candidate_id) == ("leaf", "c1")
    assert result.positive is not None
    assert result.positive.recovered_ids == POSITIVES
    assert result.negative is not None
    assert result.negative.excluded_ids == NEGATIVES
    assert result.result_size == 5012
    assert result.predicted_matches_read is True
    assert result.shortfall == []
    assert result.unresolved_negative == [UNKNOWN]
    assert result.organisms == [FALCIPARUM]


@pytest.mark.skipif(
    needs_qa_recording(
        "wdk/search_genes_by_molecular_weight.json",
        "wdk/search_genes_by_orthologs.json",
    ),
    reason=NEEDS_QA_RECORDING,
)
async def test_every_call_is_charged_and_the_leftover_is_deleted(
    account: _Account,
) -> None:
    result, _ = await _run(_request())

    assert account.deleted[0] == 77
    assert account.datasets == [POSITIVES + NEGATIVES]
    first, second = account.created_strategy_names
    assert first != second
    assert first.startswith(f"{NAME} ")
    assert second.startswith(f"{NAME} ")
    assert (result.charged_requests, result.budget) == (CHARGED, 400)


@pytest.mark.skipif(
    needs_qa_recording(
        "wdk/search_genes_by_molecular_weight.json",
        "wdk/search_genes_by_orthologs.json",
    ),
    reason=NEEDS_QA_RECORDING,
)
async def test_each_phase_reports_one_row_and_each_candidate_its_own(
    account: _Account,
) -> None:
    _, rows = await _run(_request())

    assert [(row.phase, row.candidate_id) for row in rows] == [
        ("resolved", None),
        ("uploaded", None),
        ("collected", None),
        ("measured", "c1"),
        ("assembled", None),
        ("confirmed", None),
    ]
    assert rows[3].message == (
        "GenesByMolecularWeight: 5 of 5 positives, 0 of 5 negatives, 5,012 genes"
    )
    assert rows[-1].message == (
        "The assembled strategy returns 5 of 5 positives and 0 of 5 negatives "
        "in 5,012 genes"
    )


@pytest.mark.skipif(
    needs_qa_recording(
        "wdk/search_genes_by_molecular_weight.json",
        "wdk/search_genes_by_orthologs.json",
    ),
    reason=NEEDS_QA_RECORDING,
)
async def test_the_rows_name_each_search_and_carry_the_tree(account: _Account) -> None:
    result, rows = await _run(_request())
    measured, assembled = rows[3], rows[4]

    candidate = result.measured[0].candidate
    assert (measured.data["displayName"], measured.data["basis"]) == (
        candidate.display_name,
        candidate.basis,
    )
    tree = {"kind": "leaf", "candidateId": "c1", "operator": None, "inputs": []}
    assert assembled.data["tree"] == tree
    assert rows[5].data["tree"] == tree


@pytest.mark.skipif(
    needs_qa_recording(
        "wdk/search_genes_by_molecular_weight.json",
        "wdk/search_genes_by_orthologs.json",
    ),
    reason=NEEDS_QA_RECORDING,
)
async def test_the_result_serializes_with_its_verdict(account: _Account) -> None:
    result, _ = await _run(_request())

    wire = result.model_dump(by_alias=True, mode="json")

    assert wire["separates"] is True
    assert wire["tree"] == {
        "kind": "leaf",
        "candidateId": "c1",
        "operator": None,
        "inputs": [],
    }
    assert wire["measured"][0]["candidate"]["source"] == "thread"
    assert [(s["searchName"], s["source"], s["reason"]) for s in wire["skipped"]] == [
        ("GenesByText", "annotation", "not_a_gene_search"),
        ("GenesByMolecularWeight", "catalog", "duplicate"),
        ("GenesByOrthologs", "catalog", "transform"),
        ("GeneByLocusTag", "catalog", "takes_a_gene_list"),
    ]


def test_an_id_on_both_lists_is_refused() -> None:
    with pytest.raises(ValidationError, match=POSITIVES[0]):
        _request(negatives=[POSITIVES[0]])


@pytest.mark.skipif(
    needs_qa_recording(
        "wdk/search_genes_by_molecular_weight.json",
        "wdk/search_genes_by_orthologs.json",
    ),
    reason=NEEDS_QA_RECORDING,
)
async def test_no_resolved_negative_fails_the_run(account: _Account) -> None:
    with pytest.raises(ValueError, match="no negative control resolves"):
        await _run(_request(negatives=UNHELD))


@pytest.mark.skipif(
    needs_qa_recording(
        "wdk/search_genes_by_molecular_weight.json",
        "wdk/search_genes_by_orthologs.json",
    ),
    reason=NEEDS_QA_RECORDING,
)
async def test_a_failed_resolution_fails_the_run_with_wdk_s_words(
    account: _Account, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def refused(site_id: str, gene_ids: list[str]) -> GeneResolveResult:
        return GeneResolveResult(records=[], total_count=0, error="WDK lookup failed")

    monkeypatch.setattr(separation_run, "resolve_gene_ids", refused)

    with pytest.raises(WDKError, match="WDK lookup failed"):
        await _run(_request())
    assert account.calls == []


def test_a_budget_below_the_confirm_reservation_is_refused() -> None:
    with pytest.raises(ValidationError, match="budget"):
        _request(budget=CONFIRM_RESERVATION - 1)
    assert _request(budget=CONFIRM_RESERVATION).budget == confirm_requests(MAX_CRITERIA)


@pytest.mark.skipif(
    needs_qa_recording(
        "wdk/search_genes_by_molecular_weight.json",
        "wdk/search_genes_by_orthologs.json",
    ),
    reason=NEEDS_QA_RECORDING,
)
async def test_a_run_reads_each_search_definition_once(
    account: _Account, monkeypatch: pytest.MonkeyPatch
) -> None:
    reads: list[str] = []
    client = VEuPathDBClient("https://example.invalid/service")
    body = load_recorded("search_genes_by_molecular_weight").json_body()

    async def get(path: str, **_: object) -> dict:
        reads.append(path)
        return body

    monkeypatch.setattr(client, "get", get)
    resolving = separation_run._resolve_both

    async def read_twice_then_resolve(*args: object) -> object:
        for _ in range(2):
            await client.get_search_details("transcript", "GenesByMolecularWeight")
        return await resolving(*args)

    monkeypatch.setattr(separation_run, "_resolve_both", read_twice_then_resolve)

    await _run(_request())

    assert reads == ["/record-types/transcript/searches/GenesByMolecularWeight"]


class _NoSite:
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.resolved: list[list[str]] = []
        self.opened: list[str] = []
        monkeypatch.setattr(separation_run, "resolve_gene_ids", self.resolve)
        monkeypatch.setattr(separation_run, "get_strategy_api", self.open)

    async def resolve(self, site_id: str, gene_ids: list[str]) -> GeneResolveResult:
        del site_id
        self.resolved.append(gene_ids)
        records = [
            GeneResult(gene_id=gene_id, organism=FALCIPARUM, product="kinase")
            for gene_id in gene_ids
            if gene_id != UNKNOWN
        ]
        return GeneResolveResult(records=records, total_count=len(records))

    def open(self, site_id: str) -> None:
        self.opened.append(site_id)
        msg = "the run opened the site"
        raise AssertionError(msg)


async def test_too_few_controls_return_before_any_site_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = _NoSite(monkeypatch)

    result, rows = await _run(
        _request(positives=POSITIVES[:4], negatives=NEGATIVES[:2], thread=[])
    )

    assert result == TooFewControls(positives=4, negatives=2)
    assert (result.more_negatives, result.more_positives) == (1, 1)
    assert (site.resolved, site.opened, rows) == ([], [], [])


async def test_an_unresolved_control_can_leave_too_few_before_the_upload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = _NoSite(monkeypatch)

    result, rows = await _run(_request(negatives=[NEGATIVES[0], UNKNOWN], thread=[]))

    assert result == TooFewControls(
        positives=5,
        negatives=1,
        unresolved_negative=[UNKNOWN],
        charged_requests=2 * RESOLVE_REQUESTS,
    )
    assert len(site.resolved) == 2
    assert site.opened == []
    assert [row.phase for row in rows] == ["resolved"]

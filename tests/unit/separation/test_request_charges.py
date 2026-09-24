"""Each charge of a run equals the requests the recorded plasmodb run made at that stage."""

from __future__ import annotations

import json
from collections import Counter, defaultdict, deque
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from veupathdb.auth_context import veupathdb_auth_token_ctx
from veupathdb.domain.parameters import MultiPickValue, SinglePickValue
from veupathdb.domain.strategy import CombineOp
from veupathdb.wdk import get_strategy_api, get_wdk_client

from veupathdb_mcp.controls import ControlsSearch, upload_controls
from veupathdb_mcp.gene_lookup import resolve_gene_ids
from veupathdb_mcp.separation import (
    CLEANUP_REQUESTS,
    ENRICHMENT_REQUESTS,
    FIRST_INTERSECTION_REQUESTS,
    MEASURE_REQUESTS,
    RESOLVE_REQUESTS,
    SEARCH_READ_REQUESTS,
    UPLOAD_REQUESTS,
    Candidate,
    CandidateSource,
    SeparationNode,
    SeparationUpdate,
    confirm_requests,
)
from veupathdb_mcp.separation.budget import WdkCallBudget
from veupathdb_mcp.separation.measure import (
    ControlsUnderTest,
    measure_candidates,
    read_tree,
)
from veupathdb_mcp.wdk.enrichment import BackgroundSource, enrich_gene_ids_by_value

RECORDED = Path(__file__).parent / "fixtures" / "one_run_requests.json"
ORGANISM = "Plasmodium falciparum 3D7"

type Key = tuple[str, str, str]


class _Replay:
    """Answers each request with the recorded response of the same method, path and query."""

    def __init__(self, exchanges: list[dict[str, Any]]) -> None:
        self.answers: dict[Key, deque[dict[str, Any]]] = defaultdict(deque)
        for exchange in exchanges:
            self.answers[_key(exchange)].append(exchange)
        self.seen: list[dict[str, Any]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        key = (request.method, request.url.path, request.url.query.decode())
        assert self.answers[key], f"no recorded answer left for {key}"
        exchange = self.answers[key].popleft()
        self.seen.append(exchange)
        if exchange["response_json"] is not None:
            return httpx.Response(exchange["status"], json=exchange["response_json"])
        return httpx.Response(exchange["status"], text=exchange["response_text"] or "")

    def stages(self) -> Counter[str]:
        return Counter(exchange["stage"] for exchange in self.seen)


def _key(exchange: dict[str, Any]) -> Key:
    return (exchange["method"], exchange["path"], exchange["query"])


def _recorded() -> list[dict[str, Any]]:
    return json.loads(RECORDED.read_text())["exchanges"]


@pytest.fixture
def replay(monkeypatch: pytest.MonkeyPatch) -> Iterator[_Replay]:
    answering = _Replay(_recorded())
    real = httpx.AsyncClient

    def replaying(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        return real(*args, transport=httpx.MockTransport(answering), **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", replaying)
    token = veupathdb_auth_token_ctx.set("recorded-account")
    yield answering
    veupathdb_auth_token_ctx.reset(token)


def _signal_peptide(candidate_id: str, version: str) -> Candidate:
    return Candidate(
        id=candidate_id,
        search_name="GenesWithSignalPeptide",
        display_name="GenesWithSignalPeptide",
        parameters={
            "organism": MultiPickValue(values=[ORGANISM]),
            "signalp_version": SinglePickValue(value=version),
        },
        source=CandidateSource.CATALOG,
        basis="the site's catalog",
    )


async def _ignore(update: SeparationUpdate) -> None:
    del update


async def test_every_stage_costs_the_requests_its_charge_names(
    replay: _Replay,
) -> None:
    exchanges = _recorded()
    positives = _uploaded(exchanges, "resolve_positives")
    negatives = _uploaded(exchanges, "resolve_negatives")
    api = get_strategy_api("plasmodb")

    await resolve_gene_ids("plasmodb", positives)
    await resolve_gene_ids("plasmodb", negatives)
    await api.list_strategies()
    dataset = await upload_controls(api, ControlsSearch(), positives + negatives)
    controls = ControlsUnderTest(
        positives=positives,
        negatives=negatives,
        dataset=dataset,
        strategy_name="PathFinder control separation",
    )
    budget = WdkCallBudget(limit=1000)
    await measure_candidates(
        api, [_signal_peptide("c1", "SignalP-4.1")], controls, budget, _ignore
    )
    await measure_candidates(
        api, [_signal_peptide("c2", "SignalP-4.1")], controls, budget, _ignore
    )
    tree = SeparationNode(
        kind="combine",
        operator=CombineOp.UNION,
        inputs=[
            SeparationNode(kind="leaf", candidate_id="c1"),
            SeparationNode(kind="leaf", candidate_id="c2"),
        ],
    )
    await read_tree(
        api,
        tree,
        [_signal_peptide("c1", "SignalP-4.1"), _signal_peptide("c2", "SignalP-6.0")],
        controls,
    )
    await get_wdk_client("plasmodb").get_search_details(
        "transcript", "GenesByExportPrediction", expand_params=True
    )
    await enrich_gene_ids_by_value(
        "plasmodb",
        positives,
        BackgroundSource(organism=ORGANISM),
        ["go_process", "go_function", "go_component", "pathway"],
    )

    assert replay.stages() == {
        "resolve_positives": RESOLVE_REQUESTS,
        "resolve_negatives": RESOLVE_REQUESTS,
        "list": CLEANUP_REQUESTS,
        "upload": UPLOAD_REQUESTS,
        "measure1": MEASURE_REQUESTS
        + SEARCH_READ_REQUESTS
        + FIRST_INTERSECTION_REQUESTS,
        "measure2": MEASURE_REQUESTS,
        "confirm2": confirm_requests(2),
        "param_read": SEARCH_READ_REQUESTS,
        "enrich": ENRICHMENT_REQUESTS,
    }
    assert len(replay.seen) == len(exchanges)


def _uploaded(exchanges: list[dict[str, Any]], stage: str) -> list[str]:
    """The ids a stage's recorded report returned, in the order WDK sent them."""
    report = next(
        e
        for e in exchanges
        if e["stage"] == stage and e["path"].endswith("/reports/standard")
    )
    return [record["id"][0]["value"] for record in report["response_json"]["records"]]

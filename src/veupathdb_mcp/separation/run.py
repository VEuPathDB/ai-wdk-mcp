"""One separation run: resolve, clean up, upload, collect, measure, assemble, confirm."""

from collections import Counter
from dataclasses import dataclass
from itertools import batched

from pydantic import JsonValue
from veupathdb.errors import WDKError
from veupathdb.wdk import StrategyAPI, get_strategy_api

from veupathdb_mcp.controls import (
    ControlsSearch,
    NegativeControls,
    PositiveControls,
    delete_temp_strategy,
    leftover_strategy_ids,
    upload_controls,
)
from veupathdb_mcp.gene_lookup import (
    MAX_GENE_IDS,
    GeneResult,
    normalize_gene_ids,
    resolve_gene_ids,
)
from veupathdb_mcp.separation.assemble import (
    Assembly,
    assemble,
    leaf_ids,
    rank,
    shortfall,
)
from veupathdb_mcp.separation.budget import (
    CLEANUP_REQUESTS,
    CONFIRM_RESERVATION,
    RESOLVE_REQUESTS,
    UPLOAD_REQUESTS,
    WdkCallBudget,
    confirm_requests,
)
from veupathdb_mcp.separation.enumerate import Positives, collect_candidates
from veupathdb_mcp.separation.measure import (
    ControlsUnderTest,
    measure_candidates,
    read_tree,
)
from veupathdb_mcp.separation.models import (
    Candidate,
    CandidateSource,
    MeasuredCandidate,
    SeparationProgress,
    SeparationRequest,
    SeparationResult,
    SeparationUpdate,
    SkippedCandidate,
)


@dataclass(frozen=True)
class _Resolved:
    """The ids the site holds, in the caller's order, and the ids it does not."""

    ids: list[str]
    unresolved: list[str]
    records: list[GeneResult]


async def _resolve(site_id: str, ids: list[str], budget: WdkCallBudget) -> _Resolved:
    """Resolve ids on the site. An id the site returns under another id is unresolved."""
    wanted = normalize_gene_ids(ids)
    records: dict[str, GeneResult] = {}
    for chunk in batched(wanted, MAX_GENE_IDS, strict=False):
        budget.charge(RESOLVE_REQUESTS)
        found = await resolve_gene_ids(site_id, list(chunk))
        if found.error is not None:
            raise WDKError(found.error, status=502)
        records.update((record.gene_id, record) for record in found.records)
    held = [gene_id for gene_id in wanted if gene_id in records]
    return _Resolved(
        ids=held,
        unresolved=[gene_id for gene_id in wanted if gene_id not in records],
        records=[records[gene_id] for gene_id in held],
    )


async def _resolve_both(
    site_id: str, request: SeparationRequest, budget: WdkCallBudget
) -> tuple[_Resolved, _Resolved]:
    positives = await _resolve(site_id, request.positives, budget)
    negatives = await _resolve(site_id, request.negatives, budget)
    for name, resolved in (("positive", positives), ("negative", negatives)):
        if not resolved.ids:
            msg = f"no {name} control resolves on {site_id}: {resolved.unresolved}"
            raise ValueError(msg)
    return positives, negatives


async def _clean_up(
    api: StrategyAPI, strategy_name: str, budget: WdkCallBudget
) -> None:
    """Delete the internal strategies an interrupted run under this name left."""
    budget.charge(CLEANUP_REQUESTS)
    for strategy_id in leftover_strategy_ids(
        await api.list_strategies(), strategy_name
    ):
        budget.charge(1)
        await delete_temp_strategy(api, strategy_id)


_SOURCE_WORDS = {
    CandidateSource.THREAD: "from the thread",
    CandidateSource.LITERATURE: "from the literature",
    CandidateSource.ENRICHMENT: "enrichment terms",
    CandidateSource.ANNOTATION: "product phrases",
    CandidateSource.CATALOG: "catalog searches",
}


def _collected_row(
    candidates: list[Candidate], skipped: list[SkippedCandidate]
) -> SeparationUpdate:
    by_source = Counter(c.source for c in candidates)
    by_reason = Counter(s.reason for s in skipped)
    counts = ", ".join(
        f"{by_source[source]} {words}" for source, words in _SOURCE_WORDS.items()
    )
    return SeparationUpdate(
        phase="collected",
        message=(
            f"Collected {len(candidates)} candidates: {counts}; {len(skipped)} skipped"
        ),
        data={
            "bySource": {source.value: by_source[source] for source in _SOURCE_WORDS},
            "skippedByReason": dict(sorted(by_reason.items())),
        },
    )


@dataclass(frozen=True)
class _Read:
    """The confirm read of the assembled tree, or nothing when no tree was built."""

    positive: PositiveControls | None = None
    negative: NegativeControls | None = None
    result_size: int | None = None
    matches: bool = True


async def _confirm(
    api: StrategyAPI,
    assembly: Assembly,
    candidates: list[Candidate],
    controls: ControlsUnderTest,
    budget: WdkCallBudget,
) -> _Read:
    """Build the assembled tree as one internal strategy and read its controls."""
    budget.release()
    if assembly.tree is None:
        return _Read()
    budget.charge(confirm_requests(len(leaf_ids(assembly.tree))))
    run = await read_tree(api, assembly.tree, candidates, controls)
    positive = PositiveControls.filed(controls.positives, run.returned_ids)
    negative = NegativeControls.filed(controls.negatives, run.returned_ids)
    return _Read(
        positive=positive,
        negative=negative,
        result_size=run.target_count,
        matches=frozenset(positive.recovered_ids) == assembly.recovered
        and frozenset(negative.admitted_ids) == assembly.admitted,
    )


def _assembled_row(request: SeparationRequest, assembly: Assembly) -> SeparationUpdate:
    leaves = len(leaf_ids(assembly.tree))
    message = (
        f"Assembled the {request.mode} strategy from {leaves} criteria"
        if assembly.tree is not None
        else "No measured criterion recovers a positive, so nothing was assembled"
    )
    return SeparationUpdate(
        phase="assembled",
        message=message,
        data={"mode": request.mode, "leaves": leaves},
    )


def _confirmed_row(read: _Read, budget: WdkCallBudget) -> SeparationUpdate:
    cost: dict[str, JsonValue] = {
        "chargedRequests": budget.spent,
        "budget": budget.limit,
    }
    if read.positive is None or read.negative is None:
        return SeparationUpdate(
            phase="confirmed", message="No strategy was assembled to read", data=cost
        )
    size = (
        f"{read.result_size:,} genes"
        if read.result_size is not None
        else "a result WDK did not count"
    )
    return SeparationUpdate(
        phase="confirmed",
        message=(
            f"The assembled strategy returns {read.positive.intersection_count} of "
            f"{read.positive.controls_count} positives and "
            f"{read.negative.intersection_count} of {read.negative.controls_count} "
            f"negatives in {size}"
        ),
        data={
            "recovered": read.positive.intersection_count,
            "admitted": read.negative.intersection_count,
            "size": read.result_size,
            **cost,
        },
    )


async def _measure_and_assemble(
    api: StrategyAPI,
    request: SeparationRequest,
    controls: ControlsUnderTest,
    candidates: list[Candidate],
    budget: WdkCallBudget,
    progress: SeparationProgress,
) -> tuple[list[MeasuredCandidate], list[SkippedCandidate], Assembly, _Read]:
    measured, refused = await measure_candidates(
        api, candidates, controls, budget, progress
    )
    assembly = assemble(measured, request.mode, controls.positives)
    await progress(_assembled_row(request, assembly))
    read = await _confirm(api, assembly, candidates, controls, budget)
    await progress(_confirmed_row(read, budget))
    return measured, refused, assembly, read


async def separate(
    site_id: str,
    request: SeparationRequest,
    *,
    strategy_name: str,
    progress: SeparationProgress,
) -> SeparationResult:
    """Find the strategy that separates the positives from the negatives on the site.

    Every count is read from WDK. ``strategy_name`` names the internal strategies
    the run writes and the leftovers its cleanup deletes.
    """
    budget = WdkCallBudget(limit=request.budget)
    budget.reserve(CONFIRM_RESERVATION)
    positives, negatives = await _resolve_both(site_id, request, budget)
    await progress(
        SeparationUpdate(
            phase="resolved",
            message=(
                f"Resolved {len(positives.ids)} positive and "
                f"{len(negatives.ids)} negative ids"
            ),
            data={
                "positives": len(positives.ids),
                "negatives": len(negatives.ids),
                "unresolved": len(positives.unresolved) + len(negatives.unresolved),
            },
        )
    )
    api = get_strategy_api(site_id)
    await _clean_up(api, strategy_name, budget)
    budget.charge(UPLOAD_REQUESTS)
    controls = ControlsUnderTest(
        positives=positives.ids,
        negatives=negatives.ids,
        dataset=await upload_controls(
            api, ControlsSearch(), positives.ids + negatives.ids
        ),
        strategy_name=strategy_name,
    )
    await progress(
        SeparationUpdate(
            phase="uploaded",
            message="Uploaded the controls as one dataset",
            data={"datasetIds": len(positives.ids) + len(negatives.ids)},
        )
    )
    organisms = sorted({r.organism for r in positives.records if r.organism})
    candidates, skipped = await collect_candidates(
        site_id,
        request,
        Positives(
            ids=positives.ids,
            organisms=organisms,
            products=[r.product for r in positives.records],
        ),
        budget,
    )
    await progress(_collected_row(candidates, skipped))
    measured, refused, assembly, read = await _measure_and_assemble(
        api, request, controls, candidates, budget, progress
    )
    return SeparationResult(
        site_id=site_id,
        mode=request.mode,
        organisms=organisms,
        positives=positives.ids,
        negatives=negatives.ids,
        unresolved_positive=positives.unresolved,
        unresolved_negative=negatives.unresolved,
        tree=assembly.tree,
        positive=read.positive,
        negative=read.negative,
        result_size=read.result_size,
        predicted_matches_read=read.matches,
        shortfall=shortfall(
            request.mode, assembly, read.positive, read.negative, measured
        ),
        measured=rank(measured),
        skipped=skipped + refused,
        charged_requests=budget.spent,
        budget=budget.limit,
    )

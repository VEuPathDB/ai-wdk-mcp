"""The candidate criteria of a run, from five sources, bound on the site's own searches.

Sources run in priority order, each with a quota, so no source starves the scan.
A candidate is never guessed: a parameter nothing binds skips the search.
"""

from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from veupathdb.domain.parameters import ParamValue
from veupathdb.errors import VEuPathDBError
from veupathdb.wdk import WDKSearch, encode_params

from veupathdb_mcp.catalog import (
    RADIO_OFF,
    OverrideMap,
    ParameterInfo,
    ParamFetcher,
    ParamIntent,
    UnknownParameterError,
    VagueSearchQueryError,
    get_discovery_service,
    radio_pairs,
    resolve_params_with_intent,
    search_for_searches,
    wdk_fetch_at,
)
from veupathdb_mcp.separation.budget import (
    ENRICHMENT_REQUESTS,
    SEARCH_READ_REQUESTS,
    BudgetSpentError,
    WdkCallBudget,
)
from veupathdb_mcp.separation.eligibility import (
    GENE_RECORD_CLASS,
    binding_gap,
    organism_overrides,
    params_skip,
    search_skip,
)
from veupathdb_mcp.separation.models import (
    Candidate,
    CandidateProposal,
    CandidateSource,
    SeparationRequest,
    SkippedCandidate,
    SkipReason,
)
from veupathdb_mcp.wdk.enrichment import (
    MAX_ENRICHMENT_GENE_IDS,
    BackgroundSource,
    EnrichmentAnalysisType,
    EnrichmentTerm,
    enrich_gene_ids_by_value,
)

ENRICHMENT_TYPES: tuple[EnrichmentAnalysisType, ...] = (
    "go_process",
    "go_function",
    "go_component",
    "pathway",
)
LITERATURE_HITS = 3
ENRICHMENT_QUOTA = 10
ANNOTATION_QUOTA = 5
CATALOG_RANKED = 50

TEXT_SEARCH = "GenesByText"
_PRODUCT_TEXT: OverrideMap = {"text_fields": ["product"], "document_type": "gene"}
_UNINFORMATIVE = ("unknown function", "hypothetical")
_PUTATIVE = ", putative"
_SHARED = 2


def _go_entry(term: EnrichmentTerm) -> str:
    return term.term_id


def _pathway_entry(term: EnrichmentTerm) -> str:
    return f"({term.term_id}) ({term.pathway_source})"


@dataclass(frozen=True)
class TermSearch:
    """The search an enrichment term binds into, its vocabulary parameter, and the
    vocabulary entry a term names there."""

    search_name: str
    param_name: str
    entry: Callable[[EnrichmentTerm], str]


# WDK-SITE-007: the vocabulary half of a radio pair carries the criterion.
_GO_TERM = TermSearch("GenesByGoTerm", "go_typeahead", _go_entry)
TERM_SEARCHES: Mapping[EnrichmentAnalysisType, TermSearch] = {
    "go_process": _GO_TERM,
    "go_function": _GO_TERM,
    "go_component": _GO_TERM,
    "pathway": TermSearch(
        "GenesByMetabolicPathway", "metabolic_pathway_id_with_genes", _pathway_entry
    ),
}


class CandidateSkippedError(Exception):
    """A proposal that does not become a candidate, and why."""

    def __init__(self, reason: SkipReason, detail: str = "") -> None:
        self.reason: SkipReason = reason
        self.detail = detail
        super().__init__(f"{reason}: {detail}" if detail else reason)


@dataclass(frozen=True)
class Pick:
    """A vocabulary parameter, and the one entry it takes, written as WDK lists it."""

    param_name: str
    entry: str


@dataclass(frozen=True)
class Proposal:
    """One search a source proposes, with what it states beyond the organism.

    A thread search arrives with its parameters already bound.
    """

    search_name: str
    source: CandidateSource
    basis: str
    reference: str | None = None
    stated: OverrideMap = field(default_factory=dict)
    pick: Pick | None = None
    intent: str = ""
    parameters: dict[str, ParamValue] | None = None


@dataclass(frozen=True)
class Positives:
    """The resolved positives, the organisms they belong to and their products."""

    ids: list[str]
    organisms: list[str]
    products: list[str]


def _picked(infos: list[ParameterInfo], pick: Pick) -> OverrideMap:
    """The pick's entry, or a vocabulary miss when the parameter does not list it."""
    info = next((i for i in infos if i.name == pick.param_name), None)
    listed = info is not None and any(
        option.value == pick.entry for option in info.vocabulary()
    )
    if info is None or not listed:
        msg = f"{pick.param_name} holds no entry {pick.entry}"
        raise CandidateSkippedError(reason="vocabulary_miss", detail=msg)
    if info.param_kind == "multi-pick-vocabulary":
        return {pick.param_name: [pick.entry]}
    return {pick.param_name: pick.entry}


def _overrides(
    search: WDKSearch,
    infos: list[ParameterInfo],
    proposal: Proposal,
    organisms: list[str],
) -> OverrideMap:
    """The organism, the switched-off free-text halves, and what the proposal states."""
    overrides = organism_overrides(infos, organisms)
    overrides.update(
        {
            pair.free_text: RADIO_OFF
            for pair in radio_pairs(search.properties)
            if pair.free_text not in proposal.stated
        }
    )
    overrides.update(proposal.stated)
    if proposal.pick is not None:
        overrides.update(_picked(infos, proposal.pick))
    return overrides


async def bind(
    search: WDKSearch,
    fetch_at: ParamFetcher,
    proposal: Proposal,
    organisms: list[str],
) -> dict[str, ParamValue]:
    """Every parameter of a search, bound from the organism and the proposal.

    Raises ``CandidateSkippedError`` for a search a gene list cannot intersect,
    and for one that leaves a required parameter without a value.
    """
    reason = search_skip(search)
    if reason is not None:
        raise CandidateSkippedError(reason)
    infos = await fetch_at({})
    reason = params_skip(infos)
    if reason is not None:
        raise CandidateSkippedError(reason)
    if proposal.parameters is not None:
        return dict(proposal.parameters)
    try:
        resolved = await resolve_params_with_intent(
            fetch_at=fetch_at,
            intent=ParamIntent(text=proposal.intent),
            overrides=_overrides(search, infos, proposal, organisms),
        )
    except UnknownParameterError as exc:
        raise CandidateSkippedError(reason="unbound_required", detail=str(exc)) from exc
    gap = binding_gap(resolved)
    if gap:
        raise CandidateSkippedError(reason="unbound_required", detail=gap)
    return resolved.params


def _charged(
    fetch_at: ParamFetcher, budget: WdkCallBudget, search_name: str, read: set[str]
) -> ParamFetcher:
    """Charge each read under a context, and the first read of the search in a run.

    An empty context reads the catalog's copy of the definition, fetched once.
    """

    async def fetch(context: dict[str, str]) -> list[ParameterInfo]:
        if context or search_name not in read:
            budget.charge(SEARCH_READ_REQUESTS)
            read.add(search_name)
        return await fetch_at(context)

    return fetch


def _wire_key(search_name: str, parameters: dict[str, ParamValue]) -> str:
    return f"{search_name}?{sorted(encode_params(parameters).items())}"


@dataclass
class _Collector:
    site_id: str
    organisms: list[str]
    budget: WdkCallBudget
    listing: dict[str, WDKSearch]
    candidates: list[Candidate] = field(default_factory=list)
    skipped: list[SkippedCandidate] = field(default_factory=list)
    seen: set[str] = field(default_factory=set)
    read: set[str] = field(default_factory=set)

    def skip(
        self,
        search_name: str,
        source: CandidateSource,
        basis: str,
        reason: SkipReason,
        detail: str = "",
    ) -> None:
        self.skipped.append(
            SkippedCandidate(
                search_name=search_name,
                source=source,
                basis=basis,
                reason=reason,
                detail=detail,
            )
        )

    async def _bound(self, proposal: Proposal) -> tuple[str, dict[str, ParamValue]]:
        search = self.listing.get(proposal.search_name)
        if search is None:
            detail = "the site lists no gene search by this name"
            raise CandidateSkippedError(reason="not_a_gene_search", detail=detail)
        fetch = _charged(
            wdk_fetch_at(self.site_id, GENE_RECORD_CLASS, proposal.search_name),
            self.budget,
            proposal.search_name,
            self.read,
        )
        parameters = await bind(search, fetch, proposal, self.organisms)
        if _wire_key(proposal.search_name, parameters) in self.seen:
            raise CandidateSkippedError(reason="duplicate")
        return search.display_name or search.url_segment, parameters

    async def admit(self, proposal: Proposal) -> bool:
        """Bind one proposal into a candidate. False when it is skipped."""
        try:
            display_name, parameters = await self._bound(proposal)
        except CandidateSkippedError as skipped:
            reason, detail = skipped.reason, skipped.detail
        except BudgetSpentError as spent:
            reason, detail = "budget", str(spent)
        except VEuPathDBError as refused:
            reason, detail = "wdk_refused", str(refused)
        else:
            self.seen.add(_wire_key(proposal.search_name, parameters))
            self.candidates.append(
                Candidate(
                    id=f"c{len(self.candidates) + 1}",
                    search_name=proposal.search_name,
                    display_name=display_name,
                    parameters=parameters,
                    source=proposal.source,
                    basis=proposal.basis,
                    reference=proposal.reference,
                )
            )
            return True
        self.skip(proposal.search_name, proposal.source, proposal.basis, reason, detail)
        return False


async def _literature(c: _Collector, proposals: list[CandidateProposal]) -> None:
    for proposal in proposals:
        try:
            hits = await search_for_searches(
                c.site_id, GENE_RECORD_CLASS, proposal.query, limit=LITERATURE_HITS
            )
        except VagueSearchQueryError as vague:
            c.skip(
                "",
                CandidateSource.LITERATURE,
                proposal.query,
                "source_skipped",
                vague.rejection.message,
            )
            continue
        for hit in hits:
            await c.admit(
                Proposal(
                    search_name=hit.name,
                    source=CandidateSource.LITERATURE,
                    basis=proposal.query,
                    reference=proposal.reference,
                    intent=proposal.query,
                )
            )


def _enrichment_refusal(c: _Collector, positives: Positives) -> str | None:
    """Why the site cannot enrich these positives in one call, or None."""
    if len(c.organisms) != 1:
        return f"the positives span {len(c.organisms)} organisms"
    if len(positives.ids) > MAX_ENRICHMENT_GENE_IDS:
        return (
            f"{len(positives.ids)} positives exceed the "
            f"{MAX_ENRICHMENT_GENE_IDS} one enrichment takes"
        )
    if not c.budget.affords(ENRICHMENT_REQUESTS):
        return "the budget cannot pay for the enrichment"
    return None


async def _enriched_terms(
    c: _Collector, positives: Positives
) -> list[tuple[EnrichmentAnalysisType, EnrichmentTerm]]:
    """The GO and pathway terms the site finds enriched, the smallest p-value first."""
    refusal = _enrichment_refusal(c, positives)
    if refusal is None:
        c.budget.charge(ENRICHMENT_REQUESTS)
        try:
            enrichment = await enrich_gene_ids_by_value(
                c.site_id,
                positives.ids,
                BackgroundSource(organism=c.organisms[0]),
                list(ENRICHMENT_TYPES),
            )
        except VEuPathDBError as exc:
            refusal = str(exc)
        else:
            terms = [(a.analysis_type, t) for a in enrichment.analyses for t in a.terms]
            return sorted(
                terms,
                key=lambda pair: (pair[1].p_value is None, pair[1].p_value or 0.0),
            )
    c.skip("", CandidateSource.ENRICHMENT, "enrichment", "source_skipped", refusal)
    return []


async def _enrichment(c: _Collector, positives: Positives) -> None:
    bound = 0
    offered: set[str] = set()
    for analysis_type, term in await _enriched_terms(c, positives):
        if bound >= ENRICHMENT_QUOTA:
            return
        if term.term_id in offered:
            continue
        offered.add(term.term_id)
        target = TERM_SEARCHES[analysis_type]
        bound += await c.admit(
            Proposal(
                search_name=target.search_name,
                source=CandidateSource.ENRICHMENT,
                basis=f"{term.term_id} {term.term_name}",
                pick=Pick(target.param_name, target.entry(term)),
            )
        )


def _phrase(product: str) -> str:
    text = product.strip()
    if text.lower().endswith(_PUTATIVE):
        text = text[: -len(_PUTATIVE)]
    if any(word in text.lower() for word in _UNINFORMATIVE):
        return ""
    return text


def product_phrases(products: list[str]) -> list[str]:
    """The product names two or more positives share, the most shared first."""
    counted = Counter(phrase for phrase in map(_phrase, products) if phrase)
    ranked = sorted(counted.items(), key=lambda item: (-item[1], item[0]))
    return [phrase for phrase, count in ranked if count >= _SHARED]


async def _annotation(c: _Collector, phrases: list[str]) -> None:
    for phrase in phrases[:ANNOTATION_QUOTA]:
        await c.admit(
            Proposal(
                search_name=TEXT_SEARCH,
                source=CandidateSource.ANNOTATION,
                basis=phrase,
                stated={"text_expression": f'"{phrase}"', **_PRODUCT_TEXT},
            )
        )


async def _catalog_order(c: _Collector, phrases: list[str]) -> list[str]:
    """The site's gene searches, those the positives' phrases rank first."""
    ranked: list[str] = []
    if phrases:
        try:
            hits = await search_for_searches(
                c.site_id, GENE_RECORD_CLASS, " ".join(phrases), limit=CATALOG_RANKED
            )
            ranked = [hit.name for hit in hits]
        except VagueSearchQueryError:
            ranked = []
    return list(dict.fromkeys([*ranked, *c.listing]))


async def _catalog(c: _Collector, phrases: list[str]) -> None:
    for search_name in await _catalog_order(c, phrases):
        if len(c.candidates) >= c.budget.measurements_left():
            return
        await c.admit(
            Proposal(
                search_name=search_name,
                source=CandidateSource.CATALOG,
                basis="the site's catalog",
            )
        )


async def collect_candidates(
    site_id: str,
    request: SeparationRequest,
    positives: Positives,
    budget: WdkCallBudget,
) -> tuple[list[Candidate], list[SkippedCandidate]]:
    """Every candidate the five sources propose and the site binds, and every skip."""
    listing = await get_discovery_service().get_searches(site_id, GENE_RECORD_CLASS)
    c = _Collector(
        site_id=site_id,
        organisms=positives.organisms,
        budget=budget,
        listing={search.url_segment: search for search in listing},
    )
    for thread_search in request.thread:
        await c.admit(
            Proposal(
                search_name=thread_search.search_name,
                source=CandidateSource.THREAD,
                basis="in the thread",
                parameters=thread_search.parameters,
            )
        )
    await _literature(c, request.literature)
    await _enrichment(c, positives)
    phrases = product_phrases(positives.products)
    await _annotation(c, phrases)
    await _catalog(c, phrases)
    return c.candidates, c.skipped

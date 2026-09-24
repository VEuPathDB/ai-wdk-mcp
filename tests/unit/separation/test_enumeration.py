"""The five sources propose searches, and the site's own definitions bind them."""

import pytest
from tests._support.recorded_searches import (
    gene_list_search,
    recorded_search,
    site_recorded_search,
)
from tests._support.separation_site import FALCIPARUM, RecordedCatalog, patch_site
from veupathdb.domain.parameters import MultiPickValue, SinglePickValue, StringValue

from veupathdb_mcp.catalog import (
    RADIO_OFF,
    SearchQueryRejection,
    VagueSearchQueryError,
)
from veupathdb_mcp.separation import (
    CandidateProposal,
    CandidateSource,
    SeparationRequest,
    ThreadSearch,
)
from veupathdb_mcp.separation import enumerate as enumeration
from veupathdb_mcp.separation.budget import MEASURE_REQUESTS, WdkCallBudget
from veupathdb_mcp.separation.enumerate import (
    CandidateSkippedError,
    Pick,
    Positives,
    Proposal,
    bind,
    collect_candidates,
    product_phrases,
)
from veupathdb_mcp.wdk.enrichment import (
    BackgroundSource,
    EnrichedAnalysis,
    EnrichmentAnalysisType,
    EnrichmentTerm,
    GeneIdEnrichment,
)
from veupathdb_mcp.wdk.enrichment.gene_ids import SOURCE_COLUMNS

WEIGHT = "GenesByMolecularWeight"
POSITIVES = Positives(
    ids=["PF3D7_0100100", "PF3D7_0100200"],
    organisms=[FALCIPARUM],
    products=[],
)
THREAD_WEIGHT = ThreadSearch(
    search_name=WEIGHT,
    parameters={
        "organism": MultiPickValue(values=[FALCIPARUM]),
        "min_molecular_weight": StringValue(value="10000"),
        "max_molecular_weight": StringValue(value="50000"),
    },
)


def _responses() -> list:
    return [
        recorded_search("search_genes_by_molecular_weight"),
        recorded_search("search_genes_by_orthologs"),
        gene_list_search(),
    ]


def _request(**kwargs) -> SeparationRequest:
    return SeparationRequest(
        positives=POSITIVES.ids,
        negatives=["PF3D7_0200100"],
        mode="exact",
        budget=400,
        **kwargs,
    )


def _no_terms() -> GeneIdEnrichment:
    return GeneIdEnrichment(
        site_id="plasmodb",
        gene_count=2,
        background=BackgroundSource(organism=FALCIPARUM),
        analyses=[],
    )


def test_a_product_phrase_is_one_the_positives_share() -> None:
    products = [
        "serine/threonine protein kinase, putative",
        "serine/threonine protein kinase",
        "conserved Plasmodium protein, unknown function",
        "conserved Plasmodium protein, unknown function",
        "rhoptry protein",
    ]

    assert product_phrases(products) == ["serine/threonine protein kinase"]


async def test_a_pick_binds_the_entry_its_term_names() -> None:
    search = recorded_search("search_genes_by_molecular_weight").search_data
    catalog = RecordedCatalog(_responses())
    proposal = Proposal(
        search_name=WEIGHT,
        source=CandidateSource.ENRICHMENT,
        basis="Plasmodium vivax P01",
        pick=Pick("organism", "Plasmodium vivax P01"),
    )

    parameters = await bind(
        search, catalog.wdk_fetch_at("plasmodb", "transcript", WEIGHT), proposal, []
    )

    assert parameters["organism"] == MultiPickValue(values=["Plasmodium vivax P01"])


async def test_a_term_the_vocabulary_lacks_is_a_vocabulary_miss() -> None:
    search = recorded_search("search_genes_by_molecular_weight").search_data
    catalog = RecordedCatalog(_responses())
    proposal = Proposal(
        search_name=WEIGHT,
        source=CandidateSource.ENRICHMENT,
        basis="Toxoplasma gondii ME49",
        pick=Pick("organism", "Toxoplasma gondii ME49"),
    )

    with pytest.raises(CandidateSkippedError) as skipped:
        await bind(
            search, catalog.wdk_fetch_at("plasmodb", "transcript", WEIGHT), proposal, []
        )

    assert skipped.value.reason == "vocabulary_miss"


async def test_the_thread_goes_first_and_the_catalog_copy_is_a_duplicate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_site(monkeypatch, _responses(), enrichment=_no_terms())

    candidates, skipped = await collect_candidates(
        "plasmodb",
        _request(thread=[THREAD_WEIGHT]),
        POSITIVES,
        WdkCallBudget(limit=400),
    )

    assert [(c.id, c.search_name, c.source) for c in candidates] == [
        ("c1", WEIGHT, CandidateSource.THREAD)
    ]
    assert [(s.search_name, s.source, s.reason) for s in skipped] == [
        (WEIGHT, CandidateSource.CATALOG, "duplicate"),
        ("GenesByOrthologs", CandidateSource.CATALOG, "transform"),
        ("GeneByLocusTag", CandidateSource.CATALOG, "takes_a_gene_list"),
    ]


async def test_a_literature_query_binds_its_hits_with_the_reference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_site(monkeypatch, _responses(), hits=[WEIGHT], enrichment=_no_terms())
    paper = CandidateProposal(query="small secreted proteins", reference="PMID:123")

    candidates, _ = await collect_candidates(
        "plasmodb", _request(literature=[paper]), POSITIVES, WdkCallBudget(limit=400)
    )

    assert candidates[0].source == CandidateSource.LITERATURE
    assert candidates[0].reference == "PMID:123"
    assert candidates[0].parameters["organism"] == MultiPickValue(values=[FALCIPARUM])


async def test_a_query_too_vague_to_rank_skips_the_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_site(monkeypatch, _responses(), enrichment=_no_terms())
    rejection = SearchQueryRejection(error="query_too_vague", message="too vague")

    async def vague(*args: object, **kwargs: object) -> list:
        raise VagueSearchQueryError(rejection)

    monkeypatch.setattr(enumeration, "search_for_searches", vague)
    paper = CandidateProposal(query="kin", reference="PMID:123")

    _, skipped = await collect_candidates(
        "plasmodb", _request(literature=[paper]), POSITIVES, WdkCallBudget(limit=400)
    )

    assert (skipped[0].source, skipped[0].reason, skipped[0].detail) == (
        CandidateSource.LITERATURE,
        "source_skipped",
        "too vague",
    )


async def test_a_term_whose_search_the_site_lacks_is_not_a_gene_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The catalog holds no pathway search, so the pathway term binds nothing."""
    term = _term("ec00790", "Folate biosynthesis", 0.001, "KEGG")
    enrichment = _no_terms().model_copy(
        update={
            "analyses": [
                EnrichedAnalysis(
                    analysis_type="pathway",
                    source_columns=SOURCE_COLUMNS["pathway"],
                    terms=[term],
                )
            ]
        }
    )
    patch_site(monkeypatch, _responses(), enrichment=enrichment)
    budget = WdkCallBudget(limit=400)

    _, skipped = await collect_candidates("plasmodb", _request(), POSITIVES, budget)

    assert (skipped[0].search_name, skipped[0].basis, skipped[0].reason) == (
        "GenesByMetabolicPathway",
        "ec00790 Folate biosynthesis",
        "not_a_gene_search",
    )


async def test_positives_of_two_organisms_skip_the_enrichment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_site(monkeypatch, _responses())
    two = Positives(
        ids=POSITIVES.ids, organisms=[FALCIPARUM, "Plasmodium vivax P01"], products=[]
    )

    _, skipped = await collect_candidates(
        "plasmodb", _request(), two, WdkCallBudget(limit=400)
    )

    assert (skipped[0].source, skipped[0].reason, skipped[0].detail) == (
        CandidateSource.ENRICHMENT,
        "source_skipped",
        "the positives span 2 organisms",
    )


async def test_the_catalog_takes_only_what_the_budget_can_measure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_site(monkeypatch, _responses(), enrichment=_no_terms())

    candidates, skipped = await collect_candidates(
        "plasmodb",
        _request(thread=[THREAD_WEIGHT]),
        POSITIVES,
        WdkCallBudget(limit=MEASURE_REQUESTS),
    )

    assert [c.source for c in candidates] == [CandidateSource.THREAD]
    assert [s.source for s in skipped] == [CandidateSource.ENRICHMENT]


def _term(
    term_id: str, term_name: str, p_value: float, source: str | None = None
) -> EnrichmentTerm:
    return EnrichmentTerm(
        term_id=term_id,
        term_name=term_name,
        pathway_source=source,
        gene_count=20,
        background_count=200,
        fold_enrichment=4.0,
        odds_ratio=5.0,
        p_value=p_value,
        fdr=0.01,
        bonferroni=0.02,
    )


def _enriched(
    analysis_type: EnrichmentAnalysisType, terms: list[EnrichmentTerm]
) -> EnrichedAnalysis:
    return EnrichedAnalysis(
        analysis_type=analysis_type,
        source_columns=SOURCE_COLUMNS[analysis_type],
        terms=terms,
    )


async def test_enriched_terms_bind_the_entries_their_ids_name_on_the_site(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A pathway entry reads "(<id>) (<source>)"; PWY-702 is on the sheet twice."""
    enrichment = _no_terms().model_copy(
        update={
            "analyses": [
                _enriched(
                    "go_component",
                    [_term("GO:0044217", "other organism part", 1e-9)],
                ),
                _enriched(
                    "pathway",
                    [
                        _term("PWY-702", "methionine", 1e-4, "BioCyc_MetaCyc"),
                        _term("ec00790", "Folate biosynthesis", 1e-3, "KEGG"),
                    ],
                ),
            ]
        }
    )
    patch_site(
        monkeypatch,
        [
            site_recorded_search("search_go_term"),
            site_recorded_search("search_metabolic_pathway"),
        ],
        enrichment=enrichment,
    )

    candidates, skipped = await collect_candidates(
        "plasmodb", _request(), POSITIVES, WdkCallBudget(limit=400)
    )

    enriched = [c for c in candidates if c.source == CandidateSource.ENRICHMENT]
    bound = [
        (c.search_name, c.basis, c.parameters[field])
        for c, field in zip(
            enriched,
            [
                "go_typeahead",
                "metabolic_pathway_id_with_genes",
                "metabolic_pathway_id_with_genes",
            ],
            strict=True,
        )
    ]
    assert bound == [
        (
            "GenesByGoTerm",
            "GO:0044217 other organism part",
            MultiPickValue(values=["GO:0044217"]),
        ),
        (
            "GenesByMetabolicPathway",
            "PWY-702 methionine",
            SinglePickValue(value="(PWY-702) (BioCyc_MetaCyc)"),
        ),
        (
            "GenesByMetabolicPathway",
            "ec00790 Folate biosynthesis",
            SinglePickValue(value="(ec00790) (KEGG)"),
        ),
    ]
    assert enriched[0].parameters["go_term"] == StringValue(value=RADIO_OFF)
    assert [c.parameters["organism"] for c in enriched] == [
        MultiPickValue(values=[FALCIPARUM])
    ] * 3
    assert [(s.search_name, s.source, s.reason) for s in skipped] == [
        ("GenesByGoTerm", CandidateSource.CATALOG, "unbound_required")
    ]


async def test_a_pathway_entry_the_sheet_does_not_hold_is_a_vocabulary_miss(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PWY-70 is a prefix of PWY-702, and the sheet holds no KEGG PWY-702."""
    enrichment = _no_terms().model_copy(
        update={
            "analyses": [
                _enriched(
                    "pathway",
                    [
                        _term("PWY-70", "none", 1e-4, "BioCyc_MetaCyc"),
                        _term("PWY-702", "methionine", 1e-3, "KEGG"),
                    ],
                )
            ]
        }
    )
    patch_site(
        monkeypatch,
        [site_recorded_search("search_metabolic_pathway")],
        enrichment=enrichment,
    )

    candidates, skipped = await collect_candidates(
        "plasmodb", _request(), POSITIVES, WdkCallBudget(limit=400)
    )

    assert [c.source for c in candidates] == [CandidateSource.CATALOG]
    assert [(s.search_name, s.basis, s.reason) for s in skipped] == [
        ("GenesByMetabolicPathway", "PWY-70 none", "vocabulary_miss"),
        ("GenesByMetabolicPathway", "PWY-702 methionine", "vocabulary_miss"),
    ]

"""A listing page or a structure entry never outranks a paper."""

from __future__ import annotations

from veupathdb_mcp.research.citations import (
    LiteratureFilters,
    LiteratureOutputOptions,
)
from veupathdb_mcp.research.literature.papers import ParsedPaper
from veupathdb_mcp.research.literature.processing import (
    EnrichedPaper,
    SourcePayload,
    deduplicate_and_filter,
    sort_results,
)

QUERY = (
    "PF3D7_0304600 circumsporozoite protein Plasmodium falciparum "
    "expression life cycle transcript"
)

KEYWORD_PAGE = ParsedPaper(
    title="circumsporozoite protein",
    url="https://www.biorxiv.org/keyword/circumsporozoite-protein",
    abstract=(
        "bioRxiv - the preprint server for biology, operated by openRxiv, "
        "a not-for-profit research and educational organization"
    ),
)
SCIBX_STUB = ParsedPaper(
    title="Circumsporozoite protein",
    doi="10.1038/scibx.2010.89",
    url="https://doi.org/10.1038/scibx.2010.89",
    journal_title="Science-Business eXchange",
    abstract="Science-Business eXchange",
)
BIORXIV_ARTICLE = ParsedPaper(
    title=(
        "Transcriptional control of circumsporozoite protein in "
        "Plasmodium falciparum salivary gland sporozoites"
    ),
    url="https://www.biorxiv.org/content/10.1101/2023.05.01.538912v1",
    abstract=(
        "Sporozoite maturation changes the transcript level of the "
        "circumsporozoite protein gene across the life cycle stages."
    ),
)
PDB_ENTRY = ParsedPaper(
    title="Circumsporozoite protein of Plasmodium falciparum",
    doi="10.2210/pdb8oil/pdb",
    url="https://doi.org/10.2210/pdb8oil/pdb",
    journal_title="Worldwide Protein Data Bank",
)
SEARCH_PAGE = ParsedPaper(
    title="Search results for circumsporozoite protein",
    url="https://www.medrxiv.org/search/circumsporozoite%2Bprotein",
)


def _ranked(by_source: dict[str, SourcePayload]) -> list[EnrichedPaper]:
    filtered, _ = deduplicate_and_filter(
        by_source=by_source,
        options=LiteratureOutputOptions(
            include_abstract=True,
            abstract_max_chars=2000,
            max_authors=2,
        ),
        filters=LiteratureFilters(),
    )
    return sort_results(filtered, sort="relevance", source="all", query=QUERY)


def test_the_two_papers_rank_above_the_structure_entry_and_the_listing_page() -> None:
    ranked = _ranked(
        {
            "crossref": SourcePayload(results=[SCIBX_STUB, PDB_ENTRY]),
            "biorxiv": SourcePayload(results=[KEYWORD_PAGE, BIORXIV_ARTICLE]),
        }
    )

    assert [paper.title for paper in ranked[:2]] == [
        SCIBX_STUB.title,
        BIORXIV_ARTICLE.title,
    ]
    assert sorted(paper.title for paper in ranked[2:]) == sorted(
        [KEYWORD_PAGE.title, PDB_ENTRY.title]
    )


def test_a_paper_is_an_article_and_a_landing_page_is_not() -> None:
    ranked = _ranked(
        {
            "crossref": SourcePayload(results=[SCIBX_STUB, PDB_ENTRY]),
            "biorxiv": SourcePayload(results=[KEYWORD_PAGE, BIORXIV_ARTICLE]),
        }
    )

    assert {paper.title: paper.is_article for paper in ranked} == {
        SCIBX_STUB.title: True,
        BIORXIV_ARTICLE.title: True,
        KEYWORD_PAGE.title: False,
        PDB_ENTRY.title: False,
    }


def test_a_pmid_ranks_a_paper_above_an_article_without_an_identifier() -> None:
    """The band decides first, so a weaker title with a PMID still leads."""
    indexed = ParsedPaper(
        title="Sporozoite surface antigen shedding",
        pmid="31234567",
        url="https://pubmed.ncbi.nlm.nih.gov/31234567/",
    )
    unindexed = ParsedPaper(
        title=QUERY,
        url="https://www.biorxiv.org/content/10.1101/2024.02.02.578000v1",
    )

    ranked = _ranked(
        {
            "biorxiv": SourcePayload(results=[unindexed]),
            "pubmed": SourcePayload(results=[indexed]),
        }
    )

    assert [paper.title for paper in ranked] == [indexed.title, unindexed.title]


def test_listing_pages_are_still_returned_when_they_are_the_only_hits() -> None:
    ranked = _ranked(
        {
            "biorxiv": SourcePayload(results=[KEYWORD_PAGE]),
            "medrxiv": SourcePayload(results=[SEARCH_PAGE]),
        }
    )

    assert sorted(paper.title for paper in ranked) == sorted(
        [KEYWORD_PAGE.title, SEARCH_PAGE.title]
    )


def test_a_preprint_with_no_identifier_still_outranks_a_listing_page() -> None:
    """An arXiv entry carries neither a DOI nor a PMID, and is still a work."""
    arxiv = ParsedPaper(
        title="A kinetic model of circumsporozoite protein shedding",
        url="http://arxiv.org/abs/2401.01234v1",
        abstract="The model predicts the transcript level across the life cycle.",
    )

    ranked = _ranked(
        {
            "arxiv": SourcePayload(results=[arxiv]),
            "biorxiv": SourcePayload(results=[KEYWORD_PAGE]),
        }
    )

    assert [paper.title for paper in ranked] == [arxiv.title, KEYWORD_PAGE.title]
    assert [paper.is_article for paper in ranked] == [True, False]


def test_a_host_with_no_path_is_not_a_work() -> None:
    home = ParsedPaper(
        title="bioRxiv, the preprint server for biology",
        url="https://www.biorxiv.org/",
    )
    paper = ParsedPaper(
        title="Circumsporozoite protein transcripts in sporozoites",
        url="https://openalex.org/W2741809807",
    )

    ranked = _ranked({"openalex": SourcePayload(results=[paper, home])})

    assert [(p.title, p.is_article) for p in ranked] == [
        (paper.title, True),
        (home.title, False),
    ]

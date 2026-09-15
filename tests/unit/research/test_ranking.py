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
    title="Plasmodium falciparum circumsporozoite protein (CSP)",
    doi="10.1038/scibx.2010.89",
    url="https://doi.org/10.1038/scibx.2010.89",
    journal_title="Science-Business eXchange",
    abstract="Science-Business eXchange",
)
INDEXED_PAPER = ParsedPaper(
    title=(
        "Transcriptome analysis based detection of Plasmodium falciparum "
        "development in Anopheles stephensi mosquitoes"
    ),
    doi="10.1038/s41598-018-29969-4",
    url="https://doi.org/10.1038/s41598-018-29969-4",
    abstract=(
        "We profiled the Plasmodium falciparum transcriptome across the mosquito "
        "stages and found circumsporozoite protein transcripts rising in the "
        "salivary gland sporozoite as the life cycle progresses."
    ),
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
ENCYCLOPEDIA_ENTRY = ParsedPaper(
    title="Mitosome",
    doi="10.1007/978-1-4020-6754-9_10556",
    url="https://doi.org/10.1007/978-1-4020-6754-9_10556",
    journal_title="Encyclopedia of Genetics, Genomics, Proteomics and Informatics",
    abstract="Encyclopedia of Genetics, Genomics, Proteomics and Informatics",
)
GIARDIA_PAPER = ParsedPaper(
    title=(
        "Adaptation of the late ISC pathway in the anaerobic mitochondrial "
        "organelles of Giardia intestinalis"
    ),
    doi="10.1371/journal.ppat.1010773",
    url="https://doi.org/10.1371/journal.ppat.1010773",
    abstract=(
        "The mitosome of Giardia intestinalis retains the late iron-sulfur "
        "cluster assembly pathway, and its interactome reaches the cytosol."
    ),
)
FACULTY_OPINION = ParsedPaper(
    title=(
        "Faculty Opinions recommendation of Discovery of a HapE mutation that "
        "causes azole resistance in Aspergillus fumigatus"
    ),
    doi="10.3410/f.718198602.793487982",
    url="https://doi.org/10.3410/f.718198602.793487982",
    journal_title=(
        "Faculty Opinions - Post-Publication Peer Review of the Biomedical Literature"
    ),
    abstract=(
        "Faculty Opinions - Post-Publication Peer Review of the Biomedical Literature"
    ),
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


def test_the_bands_rank_a_described_paper_first_and_the_pages_last() -> None:
    """Identifier and abstract, identifier alone, article alone, then the rest."""
    ranked = _ranked(
        {
            "crossref": SourcePayload(results=[SCIBX_STUB, PDB_ENTRY, INDEXED_PAPER]),
            "biorxiv": SourcePayload(results=[KEYWORD_PAGE, BIORXIV_ARTICLE]),
        }
    )

    assert [paper.title for paper in ranked[:3]] == [
        INDEXED_PAPER.title,
        SCIBX_STUB.title,
        BIORXIV_ARTICLE.title,
    ]
    assert sorted(paper.title for paper in ranked[3:]) == sorted(
        [KEYWORD_PAGE.title, PDB_ENTRY.title]
    )


def test_a_stub_with_no_abstract_ranks_below_a_paper_the_title_score_prefers() -> None:
    """The stub's title repeats the query, so only the band can put the paper first."""
    ranked = _ranked(
        {"crossref": SourcePayload(results=[SCIBX_STUB, INDEXED_PAPER])},
    )

    stub, paper = ranked[1], ranked[0]
    assert (stub.title, paper.title) == (SCIBX_STUB.title, INDEXED_PAPER.title)
    assert (stub.score or 0.0) > (paper.score or 0.0)
    assert (stub.rank_band, paper.rank_band) == (1, 0)


def test_a_boilerplate_abstract_is_no_abstract() -> None:
    """An abstract that only repeats the venue does not describe the work."""
    ranked = _ranked({"crossref": SourcePayload(results=[SCIBX_STUB])})

    assert ranked[0].rank_band == 1


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


def test_a_venue_name_standing_in_for_an_abstract_is_no_abstract() -> None:
    """A long venue name passes a length floor; it still describes no work."""
    ranked = _ranked(
        {"crossref": SourcePayload(results=[ENCYCLOPEDIA_ENTRY, GIARDIA_PAPER])},
    )

    assert [paper.title for paper in ranked] == [
        GIARDIA_PAPER.title,
        ENCYCLOPEDIA_ENTRY.title,
    ]
    assert (ranked[0].rank_band, ranked[1].rank_band) == (0, 1)


def test_a_recommendation_of_a_paper_is_not_the_paper() -> None:
    """The 10.3410 prefix registers recommendations, so one never outranks a work."""
    ranked = _ranked(
        {"crossref": SourcePayload(results=[FACULTY_OPINION, GIARDIA_PAPER])},
    )

    assert [paper.title for paper in ranked] == [
        GIARDIA_PAPER.title,
        FACULTY_OPINION.title,
    ]
    assert (ranked[1].is_article, ranked[1].rank_band) == (False, 3)

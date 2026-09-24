"""A site's dataset records, read from the recorded AllDatasets report, as cards."""

from __future__ import annotations

from pathlib import Path

import pytest
from veupathdb import JSONObject
from veupathdb.devtools.wdk_capture import WDKExchange

from veupathdb_mcp.catalog.catalog_metadata import (
    DATASET_REPORT_PATH,
    dataset_report_request,
    load_dataset_metadata,
)
from veupathdb_mcp.catalog.experiment_card import ExperimentCard

_RECORDED = Path(__file__).parent / "fixtures" / "plasmodb_all_datasets.json"

_KNOWLESI = "Cytoadherent and wild-type P. knowlesi (experiment 2)"
_KNOWLESI_RNASEQ = (
    "GenesByRNASeqpknoH_pknoH_Chuang_Cytoadherant_RNASeq_unstranded_ebi_rnaSeq_RSRC"
)


class _RecordedSite:
    """A client that answers the report with the recorded body."""

    def __init__(self) -> None:
        self.exchange = WDKExchange.model_validate_json(_RECORDED.read_text())
        self.posted: list[tuple[str, JSONObject]] = []

    async def post(self, path: str, *, json: JSONObject) -> JSONObject:
        self.posted.append((path, json))
        assert self.exchange.response_json is not None
        return self.exchange.response_json


@pytest.fixture(scope="module")
async def plasmodb() -> list[ExperimentCard]:
    return await load_dataset_metadata(_RecordedSite(), "plasmodb")


def _named(cards: list[ExperimentCard], name: str) -> ExperimentCard:
    return next(card for card in cards if card.name == name)


def test_the_recording_is_the_request_the_build_posts() -> None:
    recorded = WDKExchange.model_validate_json(_RECORDED.read_text())

    assert recorded.url.endswith(f"/plasmo/service{DATASET_REPORT_PATH}")
    assert recorded.request_json == dataset_report_request()


async def test_the_build_asks_for_the_attributes_and_tables_a_card_reads() -> None:
    site = _RecordedSite()

    await load_dataset_metadata(site, "plasmodb")

    assert site.posted == [(DATASET_REPORT_PATH, dataset_report_request())]
    report = dataset_report_request()["reportConfig"]
    assert report == {
        "attributes": [
            "primary_key",
            "display_name",
            "type",
            "newcategory",
            "organism_prefix",
            "short_attribution",
            "summary",
        ],
        "tables": ["References", "Publications"],
    }


def test_the_report_has_one_card_per_dataset(plasmodb: list[ExperimentCard]) -> None:
    assert len(plasmodb) == 323
    assert len({card.dataset_id for card in plasmodb}) == 323
    assert {card.site_id for card in plasmodb} == {"plasmodb"}


def test_a_card_reads_its_dataset_without_markup(
    plasmodb: list[ExperimentCard],
) -> None:
    card = _named(plasmodb, _KNOWLESI)

    assert card.dataset_id == "DS_00f985857c"
    assert card.organism == "Plasmodium knowlesi strain H"
    assert card.assay == "RNASeq"
    assert card.attribution == "Chuang et al. 2022"
    assert card.pmids == ["36056126"]
    assert card.summary == (
        "RNA Seq transcriptome analysis of Plasmodium knowlesi lines with increased "
        "iRBC cytoadhesion activity including 4-, 8-, and 24-hr samples of Pan 0 "
        "and Pan 13."
    )
    assert card.record_url == (
        "https://plasmodb.org/plasmo/app/record/dataset/DS_00f985857c"
    )


def test_a_card_names_the_gene_searches_it_feeds_on_its_site(
    plasmodb: list[ExperimentCard],
) -> None:
    card = _named(plasmodb, _KNOWLESI)

    assert card.searches == [
        "GenesByIntronJunctions",
        _KNOWLESI_RNASEQ,
        f"{_KNOWLESI_RNASEQ}DESeq",
        f"{_KNOWLESI_RNASEQ}Percentile",
    ]
    assert "IntronJunctionDynamicSearch" not in card.searches


def test_no_card_names_a_search_of_another_record_class(
    plasmodb: list[ExperimentCard],
) -> None:
    named = {search for card in plasmodb for search in card.searches}

    assert [search for search in named if "." in search] == []
    assert "IntronJunctionDynamicSearch" not in named


def test_a_dataset_without_a_category_takes_its_type(
    plasmodb: list[ExperimentCard],
) -> None:
    unnamed = sorted(card.name for card in plasmodb if not card.assay)

    assert len([card for card in plasmodb if card.assay == "isolates"]) == 24
    assert len([card for card in plasmodb if card.assay == "feature"]) == 16
    assert unnamed == [
        "Chabbert_TSS",
        "The Database of Expressed Sequence Tags (dbEST)",
    ]


def test_a_dataset_of_several_organisms_lists_them_apart(
    plasmodb: list[ExperimentCard],
) -> None:
    several = [card for card in plasmodb if card.organism.count("; ") == 13]

    assert len(several) == 2
    assert several[0].organism.split("; ")[:2] == [
        "Plasmodium berghei ANKA",
        "Plasmodium chabaudi chabaudi",
    ]


def test_a_summary_is_cut_at_six_hundred_characters(
    plasmodb: list[ExperimentCard],
) -> None:
    long = ExperimentCard(
        site_id="plasmodb",
        dataset_id="DS_x",
        name="n",
        organism="o",
        assay="a",
        summary="<p>" + "word " * 200 + "</p>",
        record_url="u",
    )

    assert max(len(card.summary) for card in plasmodb) <= 600
    assert len(long.summary) == 600
    assert "<p>" not in long.summary


def test_a_line_names_the_site_organism_assay_and_attribution(
    plasmodb: list[ExperimentCard],
) -> None:
    card = _named(plasmodb, _KNOWLESI)

    assert card.line() == (
        "plasmodb | Plasmodium knowlesi strain H | RNASeq | "
        "Cytoadherent and wild-type P. knowlesi (experiment 2) (Chuang et al. 2022)"
    )


def test_every_line_fits_one_hundred_sixty_characters(
    plasmodb: list[ExperimentCard],
) -> None:
    lines = [card.line() for card in plasmodb]

    assert max(len(line) for line in lines) <= 160
    assert all(line.startswith("plasmodb | ") for line in lines)


def test_a_line_of_several_organisms_names_the_first_and_counts_the_rest(
    plasmodb: list[ExperimentCard],
) -> None:
    card = next(card for card in plasmodb if card.organism.count("; ") == 13)

    assert card.line().startswith("plasmodb | Plasmodium berghei ANKA and 13 more | ")


def test_a_card_survives_its_own_json(plasmodb: list[ExperimentCard]) -> None:
    card = _named(plasmodb, _KNOWLESI)

    assert ExperimentCard.model_validate(card.model_dump(mode="json")) == card
    assert card.model_dump(mode="json", by_alias=True)["datasetId"] == ("DS_00f985857c")


class _OneRecordSite:
    """A client whose report holds the vectorbase record cited by a DOI alone."""

    async def post(self, path: str, *, json: JSONObject) -> JSONObject:
        del path, json
        return {
            "records": [
                {
                    "id": [{"name": "dataset_id", "value": "DS_af57b0e081"}],
                    "attributes": {"display_name": "Head samples"},
                    "tables": {
                        "References": [],
                        "Publications": [
                            {
                                "citation": "DOI linkout",
                                "dataset_id": "DS_af57b0e081",
                                "pmid": None,
                                "url": "https://doi.org/10.1007/978-3-319-24244-6_2",
                            }
                        ],
                    },
                }
            ]
        }


async def test_a_publication_without_a_pmid_keeps_its_dataset() -> None:
    cards = await load_dataset_metadata(_OneRecordSite(), "vectorbase")

    assert [card.dataset_id for card in cards] == ["DS_af57b0e081"]
    assert cards[0].pmids == []

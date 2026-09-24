"""Other sites' experiments: one index per site, one card per site at most, never the caller's."""

from __future__ import annotations

from collections import defaultdict

import pytest

from veupathdb_mcp.catalog.experiment_card import ExperimentCard
from veupathdb_mcp.catalog.experiments import (
    UnknownExperimentError,
    rank_experiments_elsewhere,
    read_experiment,
    sites_holding_organism,
    sites_publishing,
)
from veupathdb_mcp.embeddings.experiment_index import (
    experiment_index_id,
    sync_experiments,
)
from veupathdb_mcp.embeddings.fake import FakeEmbedder
from veupathdb_mcp.embeddings.record_manager import index_size

pytestmark = pytest.mark.asyncio

_EXCYSTATION = "Oocyst excystation time course"


def _card(
    site_id: str,
    dataset_id: str,
    *,
    name: str = _EXCYSTATION,
    organism: str = "Cryptosporidium parvum Iowa II",
) -> ExperimentCard:
    return ExperimentCard(
        site_id=site_id,
        dataset_id=dataset_id,
        name=name,
        organism=organism,
        assay="RNASeq",
        attribution="Lippuner et al. 2018",
        summary="Transcriptomes of sporozoites across excystation.",
        pmids=["30208916"],
        searches=[f"GenesByRNASeq{dataset_id}"],
        record_url=f"https://{site_id}.org/app/record/dataset/{dataset_id}",
    )


async def _sync(*cards: ExperimentCard) -> None:
    by_site: dict[str, list[ExperimentCard]] = defaultdict(list)
    for card in cards:
        by_site[card.site_id].append(card)
    for site_id, held in by_site.items():
        await sync_experiments(site_id, [card.index_entry() for card in held])


# Every card named _EXCYSTATION carries the same index text, so a query of that
# text scores each of them 1.0 and scores any other card near 0.
_QUERY = _card("cryptodb", "DS_any").index_text()


@pytest.fixture
def db(
    patch_app_db_engine: None,
    embedding_index_cleaner: None,
) -> None:
    del patch_app_db_engine, embedding_index_cleaner


@pytest.fixture
async def four_sites(db: None) -> None:
    del db
    await _sync(
        _card("plasmodb", "DS_p1"),
        _card("cryptodb", "DS_c1"),
        _card("cryptodb", "DS_c2"),
        _card("toxodb", "DS_t1"),
        _card("fungidb", "DS_f1", name="Hyphal growth on glucose"),
    )


async def test_elsewhere_never_names_the_callers_site(four_sites: None) -> None:
    del four_sites

    matches = await rank_experiments_elsewhere("plasmodb", _QUERY)

    assert [match.card.site_id for match in matches] == ["cryptodb", "toxodb"]
    assert [match.similarity for match in matches] == pytest.approx([1.0, 1.0])


async def test_one_site_gives_one_card_at_most(four_sites: None) -> None:
    del four_sites

    matches = await rank_experiments_elsewhere("toxodb", _QUERY)

    assert [(m.card.site_id, m.card.dataset_id) for m in matches] == [
        ("cryptodb", "DS_c1"),
        ("plasmodb", "DS_p1"),
    ]


async def test_the_limit_counts_sites(four_sites: None) -> None:
    del four_sites

    matches = await rank_experiments_elsewhere("plasmodb", _QUERY, limit=1)

    assert [match.card.site_id for match in matches] == ["cryptodb"]


async def test_a_card_under_the_floor_is_not_returned(four_sites: None) -> None:
    del four_sites

    unrelated = await rank_experiments_elsewhere("plasmodb", "Hyphal growth")
    matched = await rank_experiments_elsewhere("plasmodb", _QUERY)

    assert unrelated == []
    assert "fungidb" not in {match.card.site_id for match in matched}


async def test_the_portal_has_no_elsewhere(
    four_sites: None, fake_embedder: FakeEmbedder
) -> None:
    del four_sites
    fake_embedder.calls.clear()

    assert await rank_experiments_elsewhere("veupathdb", _QUERY) == []
    assert fake_embedder.calls == []


async def test_a_match_carries_the_card_its_site_stored(four_sites: None) -> None:
    del four_sites

    matches = await rank_experiments_elsewhere("plasmodb", _QUERY, limit=1)

    assert matches[0].card == _card("cryptodb", "DS_c1")


async def test_a_card_is_read_by_its_site_and_dataset(four_sites: None) -> None:
    del four_sites

    assert await read_experiment("toxodb", "DS_t1") == _card("toxodb", "DS_t1")


async def test_a_dataset_another_site_holds_is_not_read_here(four_sites: None) -> None:
    del four_sites

    with pytest.raises(UnknownExperimentError) as refused:
        await read_experiment("plasmodb", "DS_t1")

    assert (refused.value.site_id, refused.value.dataset_id) == ("plasmodb", "DS_t1")


async def test_a_resync_drops_the_dataset_its_site_dropped(four_sites: None) -> None:
    del four_sites

    await _sync(_card("cryptodb", "DS_c1"))

    assert await index_size(experiment_index_id("cryptodb")) == 1
    with pytest.raises(UnknownExperimentError):
        await read_experiment("cryptodb", "DS_c2")


async def test_an_empty_sync_keeps_what_the_site_holds(four_sites: None) -> None:
    del four_sites

    await sync_experiments("cryptodb", [])

    assert await index_size(experiment_index_id("cryptodb")) == 2
    assert await read_experiment("cryptodb", "DS_c2") == _card("cryptodb", "DS_c2")


async def test_a_site_holds_an_organism_one_of_its_cards_names(db: None) -> None:
    del db
    await _sync(
        _card("cryptodb", "DS_c1"),
        _card("toxodb", "DS_t1", organism="Toxoplasma gondii ME49"),
        _card(
            "toxodb",
            "DS_t2",
            organism="Neospora caninum Liverpool<br>Toxoplasma gondii GT1",
        ),
        _card("veupathdb", "DS_t1", organism="Toxoplasma gondii ME49"),
    )

    assert await sites_holding_organism("Toxoplasma gondii ME49") == ["toxodb"]
    assert await sites_holding_organism("toxoplasma gondii") == ["toxodb"]
    assert await sites_holding_organism("Neospora caninum Liverpool") == ["toxodb"]
    assert await sites_holding_organism("Cryptosporidium parvum Iowa II") == [
        "cryptodb"
    ]
    assert await sites_holding_organism("Toxoplasma gondii ME4") == []
    assert await sites_holding_organism("Plasmodium vivax P01") == []


async def test_each_dataset_names_the_component_sites_that_publish_it(
    db: None,
) -> None:
    del db
    await _sync(
        _card("cryptodb", "DS_shared"),
        _card("cryptodb", "DS_c1"),
        _card("toxodb", "DS_shared"),
        _card("toxodb", "DS_t1"),
        _card("veupathdb", "DS_shared"),
    )

    assert await sites_publishing(["DS_shared", "DS_t1", "DS_none"]) == {
        "DS_shared": ["cryptodb", "toxodb"],
        "DS_t1": ["toxodb"],
    }


async def test_no_dataset_asks_nothing_of_the_store(db: None) -> None:
    del db

    assert await sites_publishing([]) == {}

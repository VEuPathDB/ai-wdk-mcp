import pytest
from pydantic import JsonValue, ValidationError
from tests._support.busco import NF135, served_organisms
from tests._support.wdk_genes import answer_of
from veupathdb import JSONObject
from veupathdb.errors import DataParsingError

from veupathdb_mcp.audit.busco import (
    BuscoScore,
    GenomePriority,
    OrganismScores,
    ranked_genomes,
)

NF135_PROTEIN = "C:  93.0%[S:  92.5%,D:   0.5%],F:   0.1%,M:   6.9%,n:1378"
NF135_GENOME = "C:  98.4%[S:  97.8%,D:   0.6%],F:   0.3%,M:   1.3%,n:1378"


def attributes(**served: JsonValue) -> JSONObject:
    return {
        "organism_full": NF135,
        "busco_protein": NF135_PROTEIN,
        "busco_genome": NF135_GENOME,
        "busco_lineage_dataset": "aconoidasida_odb12",
        **served,
    }


def organisms_with(name: str, **served: JsonValue) -> list[JSONObject]:
    return organisms_served(
        f"<i>Plasmodium falciparum</i> {name}", attributes(**served)
    )


def organisms_served(display: str, served: JSONObject) -> list[JSONObject]:
    return [
        {**record, "attributes": served} if record["displayName"] == display else record
        for record in served_organisms()
    ]


def ranked_plasmodb() -> list[GenomePriority]:
    return ranked_genomes(answer_of(served_organisms()).records)


def test_a_served_busco_line_reads_as_its_shares_and_gene_count() -> None:
    scores = OrganismScores.model_validate(attributes())

    assert scores.protein == BuscoScore(
        complete=93.0, fragmented=0.1, missing=6.9, total=1378
    )
    assert scores.genome == BuscoScore(
        complete=98.4, fragmented=0.3, missing=1.3, total=1378
    )
    assert (scores.organism, scores.lineage) == (NF135, "aconoidasida_odb12")


@pytest.mark.parametrize("absent", [None, ""])
def test_a_score_the_site_does_not_serve_reads_as_none(absent: str | None) -> None:
    scores = OrganismScores.model_validate(attributes(busco_genome=absent))

    assert scores.genome is None


@pytest.mark.parametrize(
    "served",
    [
        "C:  93.0%[S:  92.5%,D:   0.5%],F:   0.1%,M:   6.9%",
        "C: 193.0%[S:  92.5%,D:   0.5%],F:   0.1%,M:   6.9%,n:1378",
        "93.0",
    ],
)
def test_a_busco_line_that_is_not_one_is_refused(served: str) -> None:
    with pytest.raises(ValidationError):
        OrganismScores.model_validate(attributes(busco_protein=served))


def test_one_score_with_no_lineage_is_left_out_like_any_one_score() -> None:
    scores = OrganismScores.model_validate(
        {
            "organism_full": "X y",
            "busco_protein": NF135_GENOME,
            "busco_genome": None,
            "busco_lineage_dataset": None,
        }
    )

    assert scores.priority is None


def test_pvsy56_served_with_no_lineage_leaves_the_site_ranked() -> None:
    records = organisms_served(
        "<i>Plasmodium vivax</i> PvSY56",
        {
            "organism_full": "Plasmodium vivax PvSY56",
            "busco_protein": None,
            "busco_genome": (
                "C:  94.3%[S:  94.3%,D:   0.0%],F:   2.9%,M:   2.8%,n:1378"
            ),
            "busco_lineage_dataset": None,
        },
    )

    assert len(ranked_genomes(answer_of(records).records)) == 63


@pytest.mark.parametrize("served", [5, {"url": "u", "displayText": NF135_GENOME}])
def test_a_score_that_is_not_text_is_named(served: JsonValue) -> None:
    records = organisms_with("NF135.C10", busco_genome=served)

    with pytest.raises(
        DataParsingError, match=r"source_id=TMPTX_pfalNF135C10.*busco_genome"
    ):
        ranked_genomes(answer_of(records).records)


def test_both_scores_with_no_lineage_are_refused() -> None:
    with pytest.raises(ValidationError, match="names no BUSCO lineage"):
        OrganismScores.model_validate(attributes(busco_lineage_dataset=None))


def test_the_gap_is_genome_minus_protein_completeness() -> None:
    by_name = {priority.organism: priority for priority in ranked_plasmodb()}

    nf135 = by_name[NF135]
    assert (nf135.protein.complete, nf135.genome.complete, nf135.gap) == (
        93.0,
        98.4,
        5.4,
    )
    assert by_name["Plasmodium falciparum NF166"].gap == 2.3
    assert by_name["Plasmodium falciparum 7G8 2019"].gap == 1.8
    assert by_name["Plasmodium falciparum 3D7"].gap == -0.8


def test_plasmodb_genomes_rank_by_gap_largest_first() -> None:
    ranked = ranked_plasmodb()

    assert len(ranked) == 63
    assert [(p.organism, p.gap) for p in ranked[:3]] == [
        ("Haemoproteus tartakovskyi strain SISKIN1", 27.0),
        ("Plasmodium cynomolgi strain B", 12.3),
        ("Plasmodium yoelii yoelii 17XNL", 11.8),
    ]
    assert [p.gap for p in ranked] == sorted((p.gap for p in ranked), reverse=True)
    assert {p.lineage for p in ranked} == {"aconoidasida_odb12"}
    assert "Plasmodium vivax PvSY56" not in {p.organism for p in ranked}
    assert [p.organism for p in ranked if p.gap == 0] == [
        "Plasmodium berghei ANKA",
        "Plasmodium knowlesi strain Malayan Strain Pk1 A",
        "Plasmodium praefalciparum strain G01",
        "Plasmodium reichenowi G01",
    ]


def test_toxodb_ranks_its_scored_genomes_and_leaves_out_four_unscored() -> None:
    ranked = ranked_genomes(answer_of(served_organisms("toxodb")).records)

    by_name = {p.organism: p for p in ranked}
    assert len(ranked) == 38
    assert (ranked[0].organism, ranked[0].gap) == ("Eimeria intestinalis P0_A24", 42.8)
    assert by_name["Toxoplasma gondii ME49"].gap == -0.4
    assert by_name["Toxoplasma gondii ME49"].genome.total == 461
    assert {p.lineage for p in ranked} == {"coccidia_odb12"}
    assert not {
        "Toxoplasma gondii CtCo5",
        "Toxoplasma gondii TgCATBr5",
        "Toxoplasma gondii strain ME49xCTG F1 S27",
        "Toxoplasma gondii RH 2016",
    } & set(by_name)


def test_an_organism_without_both_scores_is_left_out() -> None:
    records = organisms_with("NF135.C10", busco_genome=None)

    ranked = ranked_genomes(answer_of(records).records)

    assert len(ranked) == 62
    assert NF135 not in {priority.organism for priority in ranked}


def test_an_unreadable_record_is_named() -> None:
    records = organisms_with("NF135.C10", busco_protein="C: ninety")

    with pytest.raises(
        DataParsingError, match=r"source_id=TMPTX_pfalNF135C10.*busco_protein"
    ):
        ranked_genomes(answer_of(records).records)


def test_a_priority_serves_camel_case_with_its_gap() -> None:
    nf135 = next(p for p in ranked_plasmodb() if p.organism == NF135)

    assert nf135.model_dump(by_alias=True) == {
        "organism": NF135,
        "protein": {
            "complete": 93.0,
            "fragmented": 0.1,
            "missing": 6.9,
            "total": 1378,
        },
        "genome": {
            "complete": 98.4,
            "fragmented": 0.3,
            "missing": 1.3,
            "total": 1378,
        },
        "lineage": "aconoidasida_odb12",
        "gap": 5.4,
    }

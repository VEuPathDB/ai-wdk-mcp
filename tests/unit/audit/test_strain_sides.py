import pytest
from tests._support.audit_site import Contig
from tests._support.proteins import PROTEIN, back_translate, row
from tests._support.strain_site import (
    DD2,
    FLANK,
    INSERT,
    REFERENCE,
    STRAIN,
    StrainSite,
    strain_site,
)

from veupathdb_mcp.tools.audit_strain_tools import audit_strain_model

POLY = PROTEIN[:100] + "N" * 40 + PROTEIN[100:]
SHORT = PROTEIN[:60] + PROTEIN[140:]
LONG = PROTEIN[:100] + INSERT + PROTEIN[100:]
PARALOG = "PfDd2_2"


def relatives_at(site: StrainSite, length: int) -> None:
    site.orthologs[REFERENCE] = [
        r.model_copy(update={"protein_length": length})
        if r.organism.startswith("Plasmodium species")
        else r
        for r in site.orthologs[REFERENCE]
    ]


@pytest.mark.parametrize("relatives", [200, 240])
async def test_a_length_difference_with_no_lost_run_is_not_judged(
    monkeypatch: pytest.MonkeyPatch, relatives: int
) -> None:
    site = strain_site(monkeypatch, (PROTEIN, POLY))
    relatives_at(site, relatives)

    result = await audit_strain_model("plasmodb", STRAIN, REFERENCE)

    assert (result.lost, result.not_read) == ([], "NO_LOST_RUN")
    assert (result.dna.verdict, result.side) == ("NOT_CHECKED", "NOT_JUDGED")
    assert result.relatives.median == relatives
    assert site.windows == []


async def test_a_strain_genome_that_encodes_what_the_relatives_lack_is_reference_long(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    strain_site(monkeypatch, (PROTEIN, LONG), intron=back_translate(INSERT))

    result = await audit_strain_model("plasmodb", STRAIN, REFERENCE)

    assert result.lost == [(101, 140)]
    assert result.dna.verdict == "GENOME_ENCODES"
    assert result.dna.counts == {"model": 20, "genome_same_strand": 3}
    assert (result.side, result.relatives.median) == ("REFERENCE_LONG", 200)


async def test_a_short_strain_model_faithful_to_its_genome_is_not_judged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = strain_site(monkeypatch, (SHORT, PROTEIN))

    result = await audit_strain_model("plasmodb", STRAIN, REFERENCE)

    assert (result.dna.verdict, result.side) == ("ABSENT", "NOT_JUDGED")
    assert result.relatives.median == 200
    assert len(site.windows) == 1


def with_paralog(monkeypatch: pytest.MonkeyPatch, gap: int) -> StrainSite:
    site = strain_site(monkeypatch, (SHORT, PROTEIN))
    strain = site.rows[0]
    gene = back_translate(SHORT) + "TAA"
    paralog_dna = back_translate(PROTEIN) + "TAA"
    contig = "C" * FLANK + gene + "C" * gap + paralog_dna + "C" * FLANK
    site.contigs["pfalDd2", strain.sequence_id] = Contig.whole(contig)
    start = strain.end + gap + 1
    paralog = row(PARALOG, DD2, len(PROTEIN), start=start).model_copy(
        update={"sequence_id": strain.sequence_id, "end": start + len(paralog_dna) - 1}
    )
    site.orthologs[REFERENCE] = [*site.orthologs[REFERENCE], paralog]
    return site


async def test_a_paralog_beside_the_strain_gene_stops_the_genome_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = with_paralog(monkeypatch, 1000)

    result = await audit_strain_model("plasmodb", STRAIN, REFERENCE)

    assert (result.lost, result.not_read) == ([(61, 140)], "PARALOG_IN_WINDOW")
    assert result.nearby_paralogs == [PARALOG]
    assert (result.dna.verdict, result.side) == ("NOT_CHECKED", "NOT_JUDGED")
    assert (result.code, result.relatives.median) == (None, 200)
    assert site.models_read == []
    assert site.windows == []


@pytest.mark.parametrize(("gap", "stopped"), [(5999, True), (6000, False)])
async def test_a_paralog_stops_the_read_only_inside_the_window(
    monkeypatch: pytest.MonkeyPatch, gap: int, stopped: bool
) -> None:
    site = with_paralog(monkeypatch, gap)

    result = await audit_strain_model("plasmodb", STRAIN, REFERENCE)

    assert (result.not_read == "PARALOG_IN_WINDOW") is stopped
    assert len(site.windows) == (0 if stopped else 1)


@pytest.mark.parametrize(
    "change", [{"pseudo": True}, {"gene_type": "pseudogene", "protein_length": None}]
)
async def test_a_member_that_is_not_coding_stops_the_read_as_well(
    monkeypatch: pytest.MonkeyPatch, change: dict[str, object]
) -> None:
    site = with_paralog(monkeypatch, 1000)
    site.orthologs[REFERENCE][-1] = site.orthologs[REFERENCE][-1].model_copy(
        update=change
    )

    result = await audit_strain_model("plasmodb", STRAIN, REFERENCE)

    assert (result.not_read, result.nearby_paralogs) == ("PARALOG_IN_WINDOW", [PARALOG])
    assert site.windows == []


@pytest.mark.parametrize("change", [{"sequence_id": "other"}, {"organism": "X y Z"}])
async def test_a_member_off_the_strain_sequence_or_organism_does_not_stop_the_read(
    monkeypatch: pytest.MonkeyPatch, change: dict[str, object]
) -> None:
    site = with_paralog(monkeypatch, 1000)
    site.orthologs[REFERENCE][-1] = site.orthologs[REFERENCE][-1].model_copy(
        update=change
    )

    result = await audit_strain_model("plasmodb", STRAIN, REFERENCE)

    assert (result.not_read, result.nearby_paralogs) == (None, [])
    assert len(site.windows) == 1

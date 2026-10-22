import pytest
from scripts.record_audit_organelle import trim_statement
from tests._support.audit_fixtures import load
from tests._support.organelle_fixtures import contig, cytb_protein
from veupathdb.wdk import WDKAnswerMeta

from veupathdb_mcp.audit.codes import GeneticCode, infer_code
from veupathdb_mcp.audit.organelle import EndOverlap, check_circular_join, end_overlap

CYTB_CDS = slice(3491, 4622)
SERVED_3D7 = 5791
SERVED_NF54 = 5609
SERVED_SN01 = 5592
SERVED_7G8 = 5505
SERVED_7G82019 = 5482


async def test_the_3d7_cytb_cds_reads_the_standard_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    protein = cytb_protein()
    cds = contig("pfal3D7").sequence[CYTB_CDS]

    assert (len(cds), len(protein)) == (1131, 376)
    assert infer_code(cds, protein) == GeneticCode.STANDARD


@pytest.mark.parametrize(
    ("abbrev", "seqid", "length", "expected"),
    [
        ("pfal3D7", "Pf3D7_MIT_v3", 5967, ("INTACT_ON_THE_LINE", 0, 0, 376, 376)),
        ("pfalNF54", "CM019798.1", 6054, ("SPLIT_AT_JOIN", 87, 0, 274, 376)),
        ("pfal7G82019", "CM019769.1", 6094, ("SPLIT_AT_JOIN", 127, 0, 248, 376)),
        ("pfal7G8", "Pf7G8_MT", 6094, ("SPLIT_AT_JOIN", 127, 1, 272, 376)),
        ("pfalSN01", "PfSN01_MT", 6093, ("NOT_FOUND", 127, 0, 291, 291)),
    ],
)
async def test_the_recorded_falciparum_mitochondria(
    monkeypatch: pytest.MonkeyPatch,
    abbrev: str,
    seqid: str,
    length: int,
    expected: tuple[str, int, int, int, int],
) -> None:
    recorded = contig(abbrev)

    result = check_circular_join(
        recorded.sequence, cytb_protein(), GeneticCode.STANDARD
    )

    assert (recorded.seqid, recorded.length) == (seqid, length)
    assert (
        result.verdict,
        result.overlap_bases,
        result.overlap_mismatches,
        result.best_linear,
        result.best_circular,
    ) == expected


async def test_the_7g8_ends_overlap_127_bases_with_one_differing_base() -> None:
    mito = contig("pfal7G8").sequence

    assert mito[-127:-1] == mito[:126]
    assert (mito[-1], mito[126]) == ("T", "A")
    assert end_overlap(mito) == EndOverlap(bases=127, mismatches=1)


@pytest.mark.parametrize(
    ("overlap", "linear"), [(0, 206), (87, 206), (126, 211), (127, 212)]
)
async def test_the_3d7_circle_cut_inside_cytb_is_split_whatever_its_overlap(
    monkeypatch: pytest.MonkeyPatch, overlap: int, linear: int
) -> None:
    mito = contig("pfal3D7").sequence
    stored = mito[4000:] + mito[: 4000 + overlap]

    result = check_circular_join(stored, cytb_protein(), GeneticCode.STANDARD)

    assert (result.verdict, result.overlap_bases) == ("SPLIT_AT_JOIN", overlap)
    assert result.overlap_mismatches == 0
    assert (result.best_linear, result.best_circular) == (linear, 376)


async def test_the_nf54_contig_without_its_last_base_is_still_split(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = check_circular_join(
        contig("pfalNF54").sequence[:-1],
        cytb_protein(),
        GeneticCode.STANDARD,
    )

    assert (result.verdict, result.overlap_bases) == ("SPLIT_AT_JOIN", 86)
    assert (result.best_linear, result.best_circular) == (274, 376)


async def test_a_frameshift_near_the_cytb_end_is_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mito = contig("pfal3D7").sequence
    at = CYTB_CDS.start + 3 * 355 + 1

    result = check_circular_join(
        mito[:at] + mito[at + 1 :],
        cytb_protein(),
        GeneticCode.STANDARD,
    )

    assert result.verdict == "NOT_FOUND"
    assert (result.best_linear, result.best_circular) == (355, 355)


@pytest.mark.parametrize(
    ("window", "cut", "bases"),
    [
        ("pfalDd2_tert.json", 1755, 0),
        ("pfalNF54_piga.json", 6442, 0),
        ("pfalNF54_piga.json", 7094, 45),
    ],
)
def test_recorded_nuclear_ends_overlap_only_in_a_real_repeat(
    window: str, cut: int, bases: int
) -> None:
    dna = load(window).sequence

    assert end_overlap(dna[cut:] + dna[:cut]) == EndOverlap(bases=bases, mismatches=0)


@pytest.mark.parametrize(
    ("name", "served", "kept"),
    [
        ("pfal3D7", SERVED_3D7, 42),
        ("pfalNF54", SERVED_NF54, 5),
        ("pfalSN01", SERVED_SN01, 5),
        ("pfal7G8", SERVED_7G8, 5),
        ("pfal7G82019", SERVED_7G82019, 4),
    ],
)
def test_the_site_served_every_genome_record_and_the_contig_keeps_its_own(
    name: str, served: int, kept: int
) -> None:
    recorded = contig(name)
    meta = WDKAnswerMeta.model_validate(recorded.served_meta)

    assert (meta.total_count, meta.response_count) == (served, served)
    assert len(recorded.genes) == kept
    assert recorded.trim == trim_statement(recorded.seqid)

import pytest
from pydantic import JsonValue, ValidationError
from tests._support.proteins import row

from veupathdb_mcp.audit.codes import GeneticCode
from veupathdb_mcp.audit.length import LengthCheck
from veupathdb_mcp.audit.strain import (
    Relative,
    StrainCheck,
    StrainModelAudit,
    StrainRelatives,
    strain_relatives,
)

ENCODED = LengthCheck(
    verdict="GENOME_ENCODES",
    windows=19,
    counts={"model": 12, "genome_same_strand": 7},
    track="MMMMMMGGGGGGGMMMMMM",
    ns_in_window=0,
    at_contig_edge=False,
)
ABSENT = ENCODED.model_copy(update={"verdict": "ABSENT"})
UNREAD = LengthCheck.not_checked()
RELATIVES = StrainRelatives(
    tier="SAME_GENUS",
    members=[
        Relative(organism="P a", length=190),
        Relative(organism="P b", length=210),
    ],
    missing=None,
    copies_per_organism=1.0,
)
FEW = StrainRelatives(
    tier=None, members=[], missing="FEWER_THAN_TWO", copies_per_organism=1.0
)
RESIDUAL = StrainRelatives(
    tier=None, members=[], missing="RESIDUAL_GROUP", copies_per_organism=None
)
SHORT_CASE: dict[str, object] = {
    "lost": [(61, 140)],
    "extra": [],
    "dna": ENCODED,
    "not_read": None,
    "nearby_paralogs": [],
    "side": "STRAIN_SHORT",
    "relatives": RELATIVES,
}


def check(**changes: object) -> StrainCheck:
    return StrainCheck.model_validate({**SHORT_CASE, **changes})


def test_a_check_serves_its_runs_side_and_relatives() -> None:
    wire: JsonValue = check().model_dump(by_alias=True, mode="json")

    assert wire == {
        "lost": [[61, 140]],
        "extra": [],
        "dna": ENCODED.model_dump(by_alias=True, mode="json"),
        "notRead": None,
        "nearbyParalogs": [],
        "side": "STRAIN_SHORT",
        "relatives": {
            "tier": "SAME_GENUS",
            "members": [
                {"organism": "P a", "length": 190},
                {"organism": "P b", "length": 210},
            ],
            "missing": None,
            "copiesPerOrganism": 1.0,
            "median": 200.0,
        },
    }


@pytest.mark.parametrize(
    "changes",
    [
        {"dna": UNREAD},
        {"dna": UNREAD, "not_read": "NO_LOST_RUN", "side": "NOT_JUDGED"},
        {"lost": [], "side": "NOT_JUDGED", "dna": ABSENT},
        {"not_read": "NO_LOST_RUN"},
    ],
)
def test_the_genome_is_read_when_and_only_when_a_run_was_lost_and_nothing_stops_it(
    changes: dict[str, object],
) -> None:
    with pytest.raises(ValidationError, match="reads the strain's genome"):
        check(**changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"dna": UNREAD, "not_read": "PARALOG_IN_WINDOW", "side": "NOT_JUDGED"},
        {"nearby_paralogs": ["PfDd2_2"]},
    ],
)
def test_nearby_paralogs_are_named_when_and_only_when_they_stop_the_read(
    changes: dict[str, object],
) -> None:
    with pytest.raises(ValidationError, match="names the paralogs"):
        check(**changes)


def test_a_paralog_in_the_window_is_served_with_its_name() -> None:
    stopped = check(
        dna=UNREAD,
        not_read="PARALOG_IN_WINDOW",
        nearby_paralogs=["PfDd2_2"],
        side="NOT_JUDGED",
    )

    assert stopped.nearby_paralogs == ["PfDd2_2"]


@pytest.mark.parametrize(
    "changes",
    [
        {"dna": ABSENT},
        {"dna": ABSENT, "side": "REFERENCE_LONG"},
        {"dna": ABSENT, "side": "UNCLEAR"},
        {"dna": UNREAD, "lost": [], "not_read": "NO_LOST_RUN"},
        {"side": "NOT_JUDGED"},
    ],
)
def test_a_side_is_judged_when_and_only_when_the_genome_encodes_the_lost_run(
    changes: dict[str, object],
) -> None:
    with pytest.raises(ValidationError, match="judges a side"):
        check(**changes)


@pytest.mark.parametrize(
    ("side", "relatives"), [("NO_RELATIVES", RELATIVES), ("UNCLEAR", FEW)]
)
def test_no_relatives_is_said_when_and_only_when_there_is_no_median(
    side: str, relatives: StrainRelatives
) -> None:
    with pytest.raises(ValidationError, match="no relatives"):
        check(side=side, relatives=relatives)


@pytest.mark.parametrize(
    "changes",
    [
        {"dna": UNREAD, "not_read": "UNQUALIFIED", "side": "NOT_JUDGED"},
        {"side": "NO_RELATIVES", "relatives": RESIDUAL},
    ],
)
def test_a_pair_is_unqualified_when_and_only_when_its_group_is_residual(
    changes: dict[str, object],
) -> None:
    with pytest.raises(ValidationError, match="residual group"):
        check(**changes)


def test_a_run_is_ordered() -> None:
    with pytest.raises(ValidationError, match="a run ends at 20, before its start 41"):
        check(extra=[(41, 20)])


@pytest.mark.parametrize(
    ("fields", "named"),
    [
        ({"tier": None, "missing": None}, "a relatives set has a tier"),
        ({"missing": "FEWER_THAN_TWO"}, "a relatives set has a tier"),
        ({"tier": None, "missing": "PARALOGS"}, "lists its members only"),
        ({"copies_per_organism": None}, "copies per organism"),
        ({"copies_per_organism": 2.0}, "copies per organism"),
    ],
)
def test_relatives_state_their_set_or_why_there_is_none(
    fields: dict[str, object], named: str
) -> None:
    with pytest.raises(ValidationError, match=named):
        StrainRelatives.model_validate({**RELATIVES.model_dump(), **fields})


def test_the_relatives_of_a_residual_group_are_not_read() -> None:
    reference = row("R", "Plasmodium falciparum 3D7", 200)

    assert strain_relatives(reference, reference, None) == RESIDUAL


def test_relatives_are_the_longest_member_of_each_other_species_organism() -> None:
    reference = row("R", "Plasmodium falciparum 3D7", 200)
    group = [
        reference,
        row("D", "Plasmodium falciparum Dd2", 120),
        row("B", "Plasmodium b X", 210),
        row("A", "Plasmodium a X", 190),
    ]

    found = strain_relatives(reference, group[1], group)

    assert found.tier == "SAME_GENUS"
    assert found.members == [
        Relative(organism="Plasmodium a X", length=190),
        Relative(organism="Plasmodium b X", length=210),
    ]
    assert (found.median, found.missing, found.copies_per_organism) == (200, None, 1)


def test_a_group_with_paralogs_names_its_copies_per_organism() -> None:
    reference = row("R", "Plasmodium falciparum 3D7", 200)
    group = [reference, row("R2", "Plasmodium falciparum 3D7", 900)]
    group += [row(f"A{i}", "Plasmodium a X", 190) for i in range(2)]
    group += [row(f"B{i}", "Plasmodium b X", 210) for i in range(2)]

    found = strain_relatives(reference, group[1], group)

    assert (found.missing, found.copies_per_organism, found.members) == (
        "PARALOGS",
        2,
        [],
    )
    assert found.median is None


def test_a_group_with_one_relative_has_too_few() -> None:
    reference = row("R", "Plasmodium falciparum 3D7", 200)
    group = [reference, row("A", "Plasmodium a X", 190)]

    assert strain_relatives(reference, group[1], group) == FEW


@pytest.mark.parametrize(
    ("code", "inferred"), [(GeneticCode.STANDARD, True), (None, True)]
)
def test_a_served_check_states_a_code_only_for_a_genome_it_read(
    code: GeneticCode | None, inferred: bool
) -> None:
    with pytest.raises(ValidationError, match="states the code it read"):
        StrainModelAudit.model_validate(
            {
                **SHORT_CASE,
                "dna": UNREAD,
                "lost": [],
                "not_read": "NO_LOST_RUN",
                "side": "NOT_JUDGED",
                "gene_ids": [
                    {"given": "S", "resolved": "S"},
                    {"given": "R", "resolved": "R"},
                ],
                "strain_gene": "S",
                "reference_gene": "R",
                "strain_length": 200,
                "reference_length": 200,
                "code": code,
                "code_inferred": inferred,
            }
        )


def test_a_strain_audit_whose_gene_ids_swap_its_genes_is_invalid() -> None:
    with pytest.raises(ValidationError, match="geneIds resolve to"):
        StrainModelAudit.model_validate(
            {
                **SHORT_CASE,
                "dna": UNREAD,
                "lost": [],
                "not_read": "NO_LOST_RUN",
                "side": "NOT_JUDGED",
                "gene_ids": [
                    {"given": "R", "resolved": "R"},
                    {"given": "S", "resolved": "S"},
                ],
                "strain_gene": "S",
                "reference_gene": "R",
                "strain_length": 200,
                "reference_length": 200,
                "code": None,
                "code_inferred": False,
            }
        )

import json
from pathlib import Path

import pytest
from tests._support.audit_site import members
from tests._support.proteins import row, tight

from veupathdb_mcp.audit.genes import GeneRow
from veupathdb_mcp.audit.lengths import (
    Confirmable,
    GroupProfile,
    NotChecked,
    Relatives,
    call_length,
    classify,
    closest_reference,
    genus_of,
    relatives_median,
    relatives_of,
    species_of,
)

FIXTURES = Path(__file__).parent / "fixtures"


def piga_group() -> list[GeneRow]:
    table = json.loads((FIXTURES / "pfal3D7_piga_orthologs.json").read_text())
    members = [
        row(r["ortho_gene_source_id"], r["organism"], int(r["protein_length"]))
        for r in table
    ]
    return [row("PF3D7_1032400", "Plasmodium falciparum 3D7", 461), *members]


def test_species_and_genus_are_the_first_two_words_and_the_first_word() -> None:
    assert species_of("Plasmodium falciparum 3D7") == "Plasmodium falciparum"
    assert genus_of("Plasmodium falciparum 3D7") == "Plasmodium"
    assert species_of("Hepatocystis sp. ex Piliocolobus") == "Hepatocystis sp."


def test_a_profile_takes_the_longest_coding_row_of_each_organism() -> None:
    rows = [
        row("A1", "Plasmodium a X", 300),
        row("A2", "Plasmodium a X", 500),
        row("B", "Plasmodium b X", 400),
        row("C", "Plasmodium c X", 600),
        row("P", "Plasmodium p X", 900).model_copy(update={"pseudo": True}),
        row("R", "Plasmodium r X", 900).model_copy(update={"gene_type": "ncRNA gene"}),
        row("N", "Plasmodium n X", None),
    ]

    profile = GroupProfile.of([], members(rows))

    assert profile.organisms == 3
    assert profile.median == 500
    assert profile.copies == 1


def test_a_coding_row_without_a_pseudogene_flag_counts_in_the_profile() -> None:
    unflagged = row("U", "Plasmodium u X", 400).model_copy(update={"pseudo": None})

    assert GroupProfile.of([], members([*tight(), unflagged])).organisms == 10


def test_the_spread_is_the_interquartile_range_over_the_median() -> None:
    rows = [row(f"G{i}", f"Plasmodium s{i} X", n) for i, n in enumerate([80, 100, 120])]

    profile = GroupProfile.of([], members(rows))

    assert profile.spread == pytest.approx((120 - 80) / 100)


def test_an_empty_group_has_no_organisms() -> None:
    assert GroupProfile.of([], []).organisms == 0


def test_a_short_gene_in_a_tight_group_is_short() -> None:
    rows = [*tight(), row("ME", "Plasmodium speciesM X", 200)]
    assert classify(rows[-1], members(rows)) == "SHORT"


def test_a_long_gene_in_a_tight_group_is_long() -> None:
    rows = [*tight(), row("ME", "Plasmodium speciesM X", 700)]
    assert classify(rows[-1], members(rows)) == "LONG"


@pytest.mark.parametrize("length", [280, 400, 600])
def test_a_gene_within_the_bounds_is_typical(length: int) -> None:
    rows = [*tight(), row("ME", "Plasmodium speciesM X", length)]
    assert classify(rows[-1], members(rows)) == "TYPICAL"


def test_a_small_group_cannot_judge() -> None:
    rows = [*tight(5), row("ME", "Plasmodium speciesM X", 200)]
    assert classify(rows[-1], members(rows)) == "UNQUALIFIED"


def test_a_loose_group_cannot_judge() -> None:
    lengths = [100, 200, 300, 400, 500, 600, 700, 800, 900]
    rows = [
        row(f"G{i}", f"Plasmodium species{i} X", n) for i, n in enumerate(lengths)
    ] + [row("ME", "Plasmodium speciesM X", 50)]
    assert classify(rows[-1], members(rows)) == "UNQUALIFIED"


def test_a_group_of_two_copies_per_organism_cannot_judge() -> None:
    doubled = [r.model_copy(update={"gene": r.gene + "b"}) for r in tight()]
    rows = [*tight(), *doubled, row("ME", "Plasmodium speciesM X", 200)]
    assert classify(rows[-1], members(rows)) == "UNQUALIFIED"


@pytest.mark.parametrize(
    "update",
    [{"protein_length": None}, {"pseudo": True}, {"gene_type": "ncRNA gene"}],
)
def test_a_gene_without_a_coding_length_cannot_judge(
    update: dict[str, object],
) -> None:
    me = row("ME", "Plasmodium speciesM X", 200).model_copy(update=update)
    rows = [*tight(), me]
    assert classify(me, members(rows)) == "UNQUALIFIED"


def test_the_ratio_is_read_against_the_genus_median() -> None:
    others = [row(f"T{i}", f"Toxoplasma s{i} X", 480) for i in range(6)]
    rows = [*tight(4), *others, row("ME", "Plasmodium speciesM X", 300)]

    assert GroupProfile.of([], members(rows)).median == 480
    assert call_length([rows[-1]], members(rows)).expected == 400
    assert classify(rows[-1], members(rows)) == "TYPICAL"


def test_a_genus_with_one_other_organism_reads_the_group_median() -> None:
    others = [row(f"T{i}", f"Toxoplasma s{i} X", 400) for i in range(8)]
    rows = [*others, row("P", "Plasmodium a X", 300), row("ME", "Plasmodium b X", 260)]

    assert call_length([rows[-1]], members(rows)).expected == 400
    assert classify(rows[-1], members(rows)) == "SHORT"


def test_the_reference_prefers_the_same_species() -> None:
    rows = [
        row("ME", "Plasmodium falciparum NF54", 300),
        row("A", "Plasmodium falciparum 3D7", 461),
        row("B", "Plasmodium vivax P01", 460),
    ]
    reference = closest_reference(rows[0], members(rows))
    assert reference is not None
    assert reference.gene == "A"


def test_the_reference_prefers_the_same_genus_over_another_genus() -> None:
    rows = [
        row("ME", "Plasmodium falciparum NF54", 300),
        row("T", "Toxoplasma gondii ME49", 400),
        row("V", "Plasmodium vivax P01", 380),
    ]
    reference = closest_reference(rows[0], members(rows))
    assert reference is not None
    assert reference.gene == "V"


def test_the_reference_is_the_single_copy_member_nearest_the_expected_length() -> None:
    rows = [
        row("ME", "Plasmodium falciparum NF54", 200),
        row("A", "Plasmodium vivax P01", 380),
        row("B", "Plasmodium knowlesi H", 400),
        row("C", "Plasmodium ovale X", 450),
        row("D1", "Plasmodium yoelii X", 400),
        row("D2", "Plasmodium yoelii X", 400),
    ]
    reference = closest_reference(rows[0], members(rows))
    assert reference is not None
    assert reference.gene == "B"


def test_a_reference_tie_goes_to_the_lower_gene_id() -> None:
    rows = [
        row("ME", "Plasmodium falciparum NF54", 200),
        row("Z", "Plasmodium vivax P01", 400),
        row("A", "Plasmodium knowlesi H", 400),
    ]
    reference = closest_reference(rows[0], members(rows))
    assert reference is not None
    assert reference.gene == "A"


def test_no_reference_without_another_single_copy_organism() -> None:
    rows = [
        row("ME", "Plasmodium falciparum NF54", 200),
        row("ME2", "Plasmodium falciparum NF54", 400),
        row("D1", "Plasmodium yoelii X", 400),
        row("D2", "Plasmodium yoelii X", 400),
    ]
    assert closest_reference(rows[0], members(rows)) is None


def test_relatives_are_the_other_species_of_the_reference_genus() -> None:
    reference = row("R", "Plasmodium falciparum 3D7", 460)
    rows = [
        reference,
        row("S", "Plasmodium falciparum IT", 300),
        row("A", "Plasmodium vivax P01", 450),
        row("B", "Plasmodium knowlesi H", 470),
        row("T", "Toxoplasma gondii ME49", 900),
    ]
    found = relatives_of(reference, rows[1], members(rows))
    assert found is not None
    assert found == Relatives(
        tier="SAME_GENUS",
        lengths={"Plasmodium vivax P01": 450, "Plasmodium knowlesi H": 470},
    )
    assert found.median == 460
    assert relatives_median(reference, rows[1], members(rows)) == 460


def test_relatives_fall_back_to_other_genera() -> None:
    reference = row("R", "Plasmodium falciparum 3D7", 460)
    rows = [
        reference,
        row("A", "Plasmodium vivax P01", 450),
        row("T", "Toxoplasma gondii ME49", 900),
        row("E", "Eimeria tenella H", 700),
    ]
    found = relatives_of(reference, reference, members(rows))
    assert found is not None
    assert found == Relatives(
        tier="OTHER_GENERA",
        lengths={"Toxoplasma gondii ME49": 900, "Eimeria tenella H": 700},
    )
    assert found.median == 800
    assert relatives_median(reference, reference, members(rows)) == 800


def test_fewer_than_two_relatives_give_no_median() -> None:
    reference = row("R", "Plasmodium falciparum 3D7", 460)
    rows = [
        reference,
        row("A", "Plasmodium vivax P01", 450),
        row("T", "Toxoplasma gondii ME49", 900),
    ]
    assert relatives_of(reference, reference, members(rows)) is None
    assert relatives_median(reference, reference, members(rows)) is None


def test_the_median_leaves_out_the_model_organism_and_the_reference_organism() -> None:
    reference = row("R", "Plasmodium vivax P01", 319)
    model = row("M", "Plasmodium knowlesi H", 110)
    rows = [
        reference,
        model,
        row("F", "Plasmodium falciparum 3D7", 300),
        row("T", "Toxoplasma gondii ME49", 310),
        row("E", "Eimeria tenella H", 312),
    ]

    found = relatives_of(reference, model, members(rows))

    assert found == Relatives(
        tier="OTHER_GENERA",
        lengths={"Toxoplasma gondii ME49": 310, "Eimeria tenella H": 312},
    )
    assert relatives_median(reference, model, members(rows)) == 311.0
    assert relatives_median(reference, reference, members(rows)) == 205.0


def test_the_piga_group_does_not_call_a_cynomolgi_b_model_short() -> None:
    rows = piga_group()
    by_gene = {r.gene: r for r in rows}
    profile = GroupProfile.of([], members(rows))

    assert profile.organisms == 58
    assert by_gene["PCYB_062670"].protein_length == 266
    assert by_gene["PY03143"].protein_length == 376
    expected = call_length([by_gene["PCYB_062670"]], members(rows)).expected
    assert by_gene["PY03143"].protein_length < 0.85 * expected
    assert classify(by_gene["PCYB_062670"], members(rows)) == "UNQUALIFIED"
    assert classify(by_gene["PF3D7_1032400"], members(rows)) == "TYPICAL"
    assert classify(by_gene["HEP_00028600"], members(rows)) == "TYPICAL"
    reference = closest_reference(by_gene["PCYB_062670"], members(rows))
    assert reference is not None
    assert reference.gene == "PcyM_0621500"


def test_a_genus_alone_in_the_group_is_read_without_relatives() -> None:
    rows = piga_group()
    haemoproteus = next(r for r in rows if r.gene == "Htart_000293500")

    assert classify(haemoproteus, members(rows)) == "SHORT"


def test_a_short_gene_with_a_short_genus_relative_cannot_judge() -> None:
    relative = row("R", "Plasmodium speciesR X", 330)
    rows = [*tight(), relative, row("ME", "Plasmodium speciesM X", 200)]

    assert 0.85 * call_length([rows[-1]], members(rows)).expected > 330
    assert classify(rows[-1], members(rows)) == "UNQUALIFIED"


def test_a_short_gene_whose_relatives_reach_the_share_is_short() -> None:
    rows = [*tight(), row("R", "Plasmodium speciesR X", 340)]
    rows.append(row("ME", "Plasmodium speciesM X", 200))

    assert classify(rows[-1], members(rows)) == "SHORT"


def test_a_long_gene_with_a_long_genus_relative_cannot_judge() -> None:
    rows = [*tight(), row("R", "Plasmodium speciesR X", 470)]
    rows.append(row("ME", "Plasmodium speciesM X", 700))

    assert classify(rows[-1], members(rows)) == "UNQUALIFIED"


def test_a_long_gene_whose_relatives_stay_under_the_share_is_long() -> None:
    rows = [*tight(), row("R", "Plasmodium speciesR X", 455)]
    rows.append(row("ME", "Plasmodium speciesM X", 700))

    assert classify(rows[-1], members(rows)) == "LONG"


def test_a_group_of_short_proteins_cannot_judge() -> None:
    rows = [*tight(9, 79), row("ME", "Plasmodium speciesM X", 30)]

    assert GroupProfile.of([], members(rows)).median == 79
    assert classify(rows[-1], members(rows)) == "UNQUALIFIED"


def test_a_group_whose_median_is_eighty_can_judge() -> None:
    rows = [*tight(9, 80), row("ME", "Plasmodium speciesM X", 30)]

    assert classify(rows[-1], members(rows)) == "SHORT"


def test_an_outlier_call_holds_its_reference() -> None:
    rows = [*tight(), row("ME", "Plasmodium speciesM X", 200)]

    call = call_length([rows[-1]], members(rows))

    assert type(call) is Confirmable
    assert (call.length_class, call.reference.gene, call.ratio) == ("SHORT", "G0", 0.5)
    assert (call.profile.organisms, call.profile.median) == (10, 400)


def test_a_typical_call_names_the_reference_it_would_read() -> None:
    rows = [*tight(), row("ME", "Plasmodium speciesM X", 390)]

    call = call_length([rows[-1]], members(rows))

    assert type(call) is NotChecked
    assert call.length_class == "TYPICAL"
    assert call.reference is not None
    assert call.reference.gene == "G0"


def test_a_group_without_another_single_copy_organism_cannot_judge() -> None:
    me = row("ME", "Plasmodium speciesM X", 200)

    call = call_length([me], members([me]))

    assert type(call) is NotChecked
    assert (call.length_class, call.reference) == ("UNQUALIFIED", None)


def test_a_short_gene_beside_a_paralog_in_its_organism_cannot_judge() -> None:
    me = row("ME", "Plasmodium speciesM X", 200)
    paralog = row("ME_para", "Plasmodium speciesM X", 400)
    rows = [*tight(), me, paralog]

    assert GroupProfile.of([], members(rows)).qualifies
    assert classify(me, members(rows)) == "UNQUALIFIED"
    assert classify(me, members([*tight(), me])) == "SHORT"


def test_a_residual_group_is_not_used_as_orthology() -> None:
    rows = [
        r.model_copy(update={"ortholog_group": "OGR7r1_0001234"})
        for r in [*tight(), row("ME", "Plasmodium speciesM X", 200)]
    ]

    assert classify(rows[-1], members(rows)) == "UNQUALIFIED"


def test_a_label_that_is_no_orthology_group_is_not_used_as_orthology() -> None:
    rows = [
        r.model_copy(
            update={"ortholog_group": "N/A (orthology not determined for pseudogenes)"}
        )
        for r in [*tight(), row("ME", "Plasmodium speciesM X", 200)]
    ]

    assert classify(rows[-1], members(rows)) == "UNQUALIFIED"


def test_a_long_gene_is_not_checked_in_the_genome() -> None:
    rows = [*tight(), row("ME", "Plasmodium speciesM X", 700)]

    call = call_length([rows[-1]], members(rows))

    assert type(call) is NotChecked
    assert call.length_class == "LONG"


def test_a_confirmable_call_holds_the_lengths_it_was_read_from() -> None:
    a = row("ME1", "Plasmodium speciesM X", 200)
    b = row("ME2", "Plasmodium speciesM X", 220)

    call = call_length([a, b], members([*tight(), a, b]))

    assert type(call) is Confirmable
    assert (call.lengths, call.reference_length, call.expected) == (
        [200, 220],
        400,
        400,
    )

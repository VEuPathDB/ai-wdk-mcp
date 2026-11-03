from tests._support.variant_wire import INDEL, INDEL_ID, SNV, SNV_ID

from veupathdb_mcp.audit.frameshift import ReferenceRun, RepeatRun
from veupathdb_mcp.audit.frameshift_inputs import _homopolymer
from veupathdb_mcp.audit.variant_calls import (
    StrainCall,
    VariantCalls,
    VariantSite,
    read_sites,
    strain_samples,
)
from veupathdb_mcp.audit.windows import GenomeSource

SOURCE = GenomeSource(
    site="constructed_site", organism="constructed_genome", seqid="constructed_seq"
)
SERVED_SAMPLES = {row.strain for row in INDEL.rows}


def test_the_recorded_records_hold_their_attributes_and_their_537_rows() -> None:
    assert (INDEL.variant_type, INDEL.reference_allele, INDEL.frame_effect) == (
        "MIXED",
        "GAGGAAA",
        "inframe_deletion",
    )
    assert (SNV.variant_type, SNV.reference_allele, SNV.frame_effect) == (
        "SNV",
        None,
        None,
    )
    assert len(SERVED_SAMPLES) == 537


def test_the_served_samples_match_the_genomes_that_name_them() -> None:
    assert strain_samples("pfal3D7", SERVED_SAMPLES) == ["3D7_WTSI"]
    assert strain_samples("pfalDd2", SERVED_SAMPLES) == ["DD2_WTSI", "Dd2-1"]
    assert strain_samples("pfal7G8", SERVED_SAMPLES) == ["7G8_2", "7G8_WTSI"]
    assert strain_samples("pfal7G8-2019", SERVED_SAMPLES) == ["7G8_2", "7G8_WTSI"]
    assert strain_samples("pfalKE01", SERVED_SAMPLES) == ["KE01"]
    assert strain_samples("pfalNF54", SERVED_SAMPLES) == []
    assert strain_samples("pfalNF135C10", SERVED_SAMPLES) == []


def test_a_multi_word_abbreviation_matches_on_its_strain_name() -> None:
    assert strain_samples("aaegLVP_AGWG", {"LVP_AGWG"}) == ["LVP_AGWG"]


def test_a_sample_does_not_match_by_a_prefix_of_its_name() -> None:
    assert strain_samples("pfalKH01", {"KH012", "KH0"}) == []
    assert strain_samples("pfalIT", {"ITALY_1"}) == []


def test_each_record_is_stated_as_served_for_every_matched_sample() -> None:
    sites, samples = read_sites("pfalDd2", [INDEL, SNV])

    assert samples == ["DD2_WTSI", "Dd2-1"]
    assert sites == [
        VariantSite(
            variant=INDEL_ID,
            variant_type="MIXED",
            indel_ref_allele="GAGGAAA",
            indel_frame_effect="inframe_deletion",
            calls=[
                StrainCall(
                    sample=row.strain,
                    genotype=row.genotype,
                    allele=row.allele,
                    depth=row.depth,
                    read_frequency=row.read_frequency,
                )
                for name in samples
                for row in INDEL.rows
                if row.strain == name
            ],
        ),
        VariantSite(
            variant=SNV_ID,
            variant_type="SNV",
            indel_ref_allele=None,
            indel_frame_effect=None,
            calls=[
                StrainCall(
                    sample=row.strain,
                    genotype=row.genotype,
                    allele=row.allele,
                    depth=row.depth,
                    read_frequency=row.read_frequency,
                )
                for name in samples
                for row in SNV.rows
                if row.strain == name
            ],
        ),
    ]
    assert [call.genotype for call in sites[0].calls] == ["0", "0"]


def test_the_recorded_row_that_does_not_fit_the_effect_is_stated_unjudged() -> None:
    sites, _ = read_sites("pfalRV", [INDEL])

    [call] = [c for c in sites[0].calls if c.sample == "RV_3630"]
    assert (call.genotype, call.allele) == ("1", "A")
    assert sites[0].indel_frame_effect == "inframe_deletion"


def test_a_strain_no_row_names_holds_no_call_and_keeps_the_records() -> None:
    sites, samples = read_sites("pfalNF54", [SNV])

    assert samples == []
    assert [(site.variant, site.calls) for site in sites] == [(SNV_ID, [])]


def test_no_record_holds_no_site() -> None:
    assert read_sites("pfalDd2", []) == ([], [])


def calls(sites: list[VariantSite], bases: int | None) -> VariantCalls:
    return VariantCalls(
        site="constructed_site",
        organism="constructed organism",
        seqid="constructed_seq",
        start=9,
        end=11,
        sites=sites,
        samples=[],
        homopolymer_bases=bases,
    )


def site_of(kind: str) -> VariantSite:
    return VariantSite(
        variant="constructed_variant",
        variant_type=kind,
        indel_ref_allele=None,
        indel_frame_effect=None,
        calls=[],
    )


def test_a_long_run_with_no_indel_record_says_little() -> None:
    assert calls([], 7).calls_say_little
    assert calls([site_of("SNV")], 28).calls_say_little


def test_a_short_run_or_no_homopolymer_makes_no_such_statement() -> None:
    assert not calls([], 6).calls_say_little
    assert not calls([], None).calls_say_little


def test_a_long_run_with_an_indel_record_makes_no_such_statement() -> None:
    assert not calls([site_of("MIXED")], 28).calls_say_little


def constructed_run(bases: int) -> ReferenceRun:
    return ReferenceRun(
        gene="constructed_gene",
        source=SOURCE,
        strand="+",
        start=1,
        end=bases,
        bases=bases,
    )


def test_the_homopolymer_length_is_the_longer_of_the_two_runs() -> None:
    run = RepeatRun(unit="A", bases=6, start=1, end=6)

    assert _homopolymer(run, constructed_run(7)) == 7
    assert _homopolymer(run.model_copy(update={"bases": 8}), constructed_run(7)) == 8


def test_a_tandem_repeat_or_no_run_is_no_homopolymer() -> None:
    tandem = RepeatRun(unit="AC", bases=8, start=1, end=8)

    assert _homopolymer(tandem, constructed_run(8)) is None
    assert _homopolymer(None, constructed_run(8)) is None

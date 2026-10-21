from pathlib import Path

import pytest
from scripts.record_audit_anatomy import (
    RECORD_ATTRIBUTES,
    SITE,
    TARGETS,
    AnatomyRecording,
    spans,
    write_recordings,
)
from scripts.record_audit_fixtures import GeneLocation
from tests._support.anatomy_site import recording
from veupathdb.jbrowse import GenomeWindow
from veupathdb.wdk import WDKRecordInstance


def place(start: int, end: int) -> GeneLocation:
    return GeneLocation(
        sequence_id="s", start_min=start, end_max=end, strand_plus_minus="-"
    )


def test_the_targets_are_the_two_nf54_pseudogenes_and_their_3d7_genes() -> None:
    assert SITE == "plasmodb"
    assert [(t.file, t.strain_gene, t.reference_gene) for t in TARGETS] == [
        (
            "anatomy_pfalNF54_piga.json",
            "PfNF54_100037200:pseudogene",
            "PF3D7_1032400",
        ),
        (
            "anatomy_pfalNF54_pagm.json",
            "PfNF54_110034300:pseudogene",
            "PF3D7_1130000",
        ),
    ]


def test_a_gene_record_is_read_with_its_location_organism_and_abbreviation() -> None:
    assert RECORD_ATTRIBUTES == [
        "sequence_id",
        "start_min",
        "end_max",
        "strand_plus_minus",
        "organismAbbrev",
        "organism_full",
    ]


def test_the_reference_span_is_the_gene_and_the_strain_span_is_padded() -> None:
    assert spans(place(100, 200), place(5000, 6000)) == [(100, 200), (2000, 9000)]


@pytest.mark.parametrize("file", [target.file for target in TARGETS])
def test_each_recording_holds_the_windows_its_spans_name(file: str) -> None:
    recorded = recording(file)
    places = [
        GeneLocation.model_validate(
            WDKRecordInstance.model_validate(recorded.records[gene]).attributes
        )
        for gene in (recorded.reference_gene, recorded.strain_gene)
    ]

    assert [(w.start, w.end) for w in recorded.windows] == spans(*places)
    assert recorded.contig_length >= recorded.windows[1].end


def test_a_recording_round_trips_through_its_file(tmp_path: Path) -> None:
    recorded = AnatomyRecording(
        site=SITE,
        strain_gene="g:pseudogene",
        reference_gene="r",
        records={"r": {"attributes": {"organismAbbrev": "pfal3D7"}}},
        windows=[GenomeWindow(seqid="s", start=7, sequence="ACGT")],
        contig_length=40,
    )

    write_recordings(tmp_path, {"a.json": recorded})

    text = (tmp_path / "a.json").read_text()
    assert AnatomyRecording.model_validate_json(text) == recorded
    assert '"sequence": "ACGT"' in text

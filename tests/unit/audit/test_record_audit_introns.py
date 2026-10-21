from pathlib import Path

import pytest
from scripts.record_audit_introns import TARGETS, IntronWire, write_wire
from tests._support.audit_wire import answers
from tests._support.intron_wire import FIXTURES, load_introns

from veupathdb_mcp.audit.genes import rows_of
from veupathdb_mcp.audit.introns_inputs import genome_region, junction_region


def test_the_targets_are_pkac_on_plasmodb_and_dmaw_on_fungidb() -> None:
    assert {name: (t.site, t.gene, t.file) for name, t in TARGETS.items()} == {
        "pkac": ("plasmodb", "PcyM_0736700", "introns_pcynM_pkac.json"),
        "dmaw": ("fungidb", "Afu2g18040", "introns_afumAf293_dmaw.json"),
    }


@pytest.mark.parametrize("name", sorted(TARGETS))
def test_a_recording_holds_the_regions_the_reader_asks_for(name: str) -> None:
    wire = load_introns(TARGETS[name].file)
    [row] = rows_of(answers(wire.gene_answers)[0], "GeneByLocusTag")

    assert (wire.site, wire.gene) == (TARGETS[name].site, TARGETS[name].gene)
    assert (row.sequence_id, wire.junction_region) == (
        wire.junction_seqid,
        junction_region(row),
    )
    start, end = genome_region(row)
    assert (wire.window_start, wire.window_start + len(wire.window) - 1) == (
        start,
        end,
    )


def test_a_written_recording_reads_back_unchanged(tmp_path: Path) -> None:
    wire = IntronWire(
        site="plasmodb",
        gene="g1",
        gene_answers=[],
        model_record={"attributes": {"organismAbbrev": "pcynM"}},
        protein_answers=[],
        junction_tracks={"tracks": []},
        junction_seqid="PcyM_07",
        junction_region=(1, 9),
        junction_lines={"track.gff.gz": ["PcyM_07\tVEuPathDB\tintronJunction"]},
        window_start=1,
        window="ACGT",
        ortholog_record={"tables": {"Orthologs": []}},
        ortholog_protein_answers=[],
    )

    write_wire(tmp_path, "introns_g1.json", wire)

    assert (
        IntronWire.model_validate_json((tmp_path / "introns_g1.json").read_text())
        == wire
    )
    assert not (FIXTURES / "introns_g1.json").exists()

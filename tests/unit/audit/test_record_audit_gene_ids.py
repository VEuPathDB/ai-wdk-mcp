from pathlib import Path

from scripts.record_audit_gene_ids import (
    FILE,
    GIVEN,
    SEARCH_PATH,
    SITE,
    GeneIdRecording,
    write_recording,
)
from tests._support.wdk_genes import FIXTURES

from veupathdb_mcp.audit.gene_ids import TEXT_SEARCH


def test_the_target_is_the_plain_id_of_the_nf54_piga_pseudogene() -> None:
    assert (SITE, GIVEN, FILE) == (
        "plasmodb",
        "PfNF54_100037200",
        "gene_ids_pfalNF54_piga.json",
    )
    assert SEARCH_PATH == "/record-types/transcript/searches/GenesByText"
    assert TEXT_SEARCH == "GenesByText"


def test_a_recording_is_written_as_it_reads_back(tmp_path: Path) -> None:
    recorded = GeneIdRecording.model_validate_json((FIXTURES / FILE).read_text())

    write_recording(tmp_path / "out", recorded)

    written = (tmp_path / "out" / FILE).read_text()
    assert GeneIdRecording.model_validate_json(written) == recorded
    assert written == (FIXTURES / FILE).read_text()

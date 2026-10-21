import json
from pathlib import Path

import pytest
from scripts.record_audit_pseudogene_calls import (
    GENOMES,
    SITE,
    genome_request,
    write_answers,
)
from tests._support.wdk_genes import answer_of, coding, serve

from veupathdb_mcp.audit.genes import genes_of_genome

NF54 = "Plasmodium falciparum NF54"


def test_the_recording_reads_the_nf54_and_3d7_genomes_of_plasmodb() -> None:
    assert SITE == "plasmodb"
    assert GENOMES == {
        "pseudogene_calls_pfalNF54.json": NF54,
        "pseudogene_calls_pfal3D7.json": "Plasmodium falciparum 3D7",
    }


async def test_the_recorded_request_is_the_genome_report_the_check_reads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = serve(monkeypatch, [answer_of([coding()])])

    await genes_of_genome(SITE, NF54)

    [(record_type, search_name, config, report)] = site.searches
    assert (record_type, search_name, config, report) == (
        "transcript",
        *genome_request(NF54),
    )
    assert config.parameters == {"organism": json.dumps([NF54])}


def test_a_recorded_answer_is_written_as_served(tmp_path: Path) -> None:
    answer = answer_of([coding()])

    write_answers(tmp_path, {"g.json": answer})

    written = (tmp_path / "g.json").read_text()
    assert json.loads(written) == answer.model_dump(mode="json", by_alias=True)
    assert "\n" not in written.rstrip("\n")

import json
from pathlib import Path

from scripts.record_audit_busco import fixture_name, served_records
from scripts.record_audit_fixtures import write_served
from tests._support.wdk_genes import answer_of
from veupathdb.wdk import WDKAnswer

NF135 = {
    "displayName": "<i>Plasmodium falciparum</i> NF135.C10",
    "id": [
        {"name": "source_id", "value": "TMPTX_pfalNF135C10"},
        {"name": "project_id", "value": "PlasmoDB"},
    ],
    "recordClassName": "OrganismRecordClasses.OrganismRecordClass",
    "attributes": {
        "organism_full": "Plasmodium falciparum NF135.C10",
        "busco_protein": "C:  93.0%[S:  92.5%,D:   0.5%],F:   0.1%,M:   6.9%,n:1378",
        "busco_genome": "C:  98.4%[S:  97.8%,D:   0.6%],F:   0.3%,M:   1.3%,n:1378",
        "busco_lineage_dataset": "aconoidasida_odb12",
    },
    "tables": {},
    "tableErrors": [],
}


def test_an_organism_report_is_written_as_served_under_its_site(
    tmp_path: Path,
) -> None:
    write_served(tmp_path, {fixture_name("toxodb"): served_records(answer_of([NF135]))})

    written = json.loads((tmp_path / "busco_toxodb.json").read_text())

    assert written == [NF135]
    assert answer_of(written) == WDKAnswer.model_validate(
        {"meta": {"totalCount": 1, "responseCount": 1}, "records": [NF135]}
    )

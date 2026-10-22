"""Record the gene record types, gene records and organism report the evidence tests
read from QA sites.

Run it from the repository root as the test account (WDK_TEST_TOKEN, or
WDK_TEST_EMAIL and WDK_TEST_PASSWORD):
``uv run python scripts/record_audit_evidence.py [--out DIR]``.
"""

import argparse
import asyncio
import json
from collections.abc import Mapping
from pathlib import Path

from pydantic import BaseModel, ConfigDict, JsonValue
from scripts.record_audit_fixtures import FIXTURES, act_as_the_test_account
from veupathdb.devtools import use_qa_sites
from veupathdb.wdk import close_all_clients, get_wdk_client

from veupathdb_mcp.audit.evidence import requested_tables
from veupathdb_mcp.audit.evidence_inputs import GENOME_ATTRIBUTES
from veupathdb_mcp.audit.gene_models import ORGANISM_ATTRIBUTE, gene_record
from veupathdb_mcp.audit.genes import organism_report
from veupathdb_mcp.wdk.gene_record_type import GENE_RECORD_TYPE_PATH, GeneRecordType

GENOME_SITE = "plasmodb"
GENOMES_FILE = "evidence_plasmodb_genomes.json"


class GeneTarget(BaseModel):
    model_config = ConfigDict(frozen=True)

    site: str
    gene: str
    file: str


GENES = [
    GeneTarget(
        site="plasmodb", gene="PF3D7_1032400", file="evidence_pfal3D7_piga.json"
    ),
    GeneTarget(site="plasmodb", gene="PF3D7_1343700", file="evidence_pfal3D7_k13.json"),
    GeneTarget(site="fungidb", gene="Afu2g18040", file="evidence_afumAf293_dmaw.json"),
    GeneTarget(
        site="tritrypdb", gene="LmjF.35.3010", file="evidence_lmajFriedlin_glo1.json"
    ),
]
RECORD_TYPE_SITES = ["plasmodb", "fungidb", "tritrypdb"]


def served_tables(record_type: JsonValue) -> JsonValue:
    served: JsonValue = GeneRecordType.model_validate(record_type).model_dump(
        mode="json", by_alias=True
    )
    return served


def write_bodies(into: Path, bodies: Mapping[str, JsonValue]) -> None:
    into.mkdir(parents=True, exist_ok=True)
    for name, body in bodies.items():
        (into / name).write_text(json.dumps(body) + "\n")


async def _served(bodies: dict[str, JsonValue]) -> None:
    declared: dict[str, list[str]] = {}
    for site in RECORD_TYPE_SITES:
        served = await get_wdk_client(site).get(GENE_RECORD_TYPE_PATH)
        bodies[f"evidence_{site}_tables.json"] = served_tables(served)
        names = GeneRecordType.model_validate(served).names
        if names is None:
            msg = f"the gene record type of {site} declares no tables"
            raise ValueError(msg)
        declared[site] = names
    for target in GENES:
        record = await gene_record(
            target.site,
            target.gene,
            [ORGANISM_ATTRIBUTE],
            requested_tables(declared[target.site]),
        )
        bodies[target.file] = record.model_dump(mode="json", by_alias=True)
    answer = await organism_report(GENOME_SITE, GENOME_ATTRIBUTES)
    bodies[GENOMES_FILE] = [
        record.model_dump(mode="json", by_alias=True) for record in answer.records
    ]


async def record(into: Path) -> None:
    use_qa_sites()
    await act_as_the_test_account()
    bodies: dict[str, JsonValue] = {}
    try:
        await _served(bodies)
    finally:
        await close_all_clients()
    write_bodies(into, bodies)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=FIXTURES)
    arguments = parser.parse_args()
    asyncio.run(record(arguments.out))

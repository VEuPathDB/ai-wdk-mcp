"""Record the gene reports of a strain genome and its reference genome that the
pseudogene-call tests read from a QA site.

Run it from the repository root as the test account (WDK_TEST_TOKEN, or
WDK_TEST_EMAIL and WDK_TEST_PASSWORD):
``uv run python scripts/record_audit_pseudogene_calls.py [--out DIR]``.
"""

import argparse
import asyncio
import json
from collections.abc import Mapping
from pathlib import Path

from scripts.record_audit_fixtures import FIXTURES, act_as_the_test_account
from veupathdb import JSONObject
from veupathdb.devtools import use_qa_sites
from veupathdb.wdk import (
    WDKAnswer,
    WDKSearchConfig,
    close_all_clients,
    get_wdk_client,
)

from veupathdb_mcp.audit import GENE_ATTRIBUTES
from veupathdb_mcp.audit.genes import GENOME_SEARCH

SITE = "plasmodb"
GENOME_RECORDS = 400000
GENOMES = {
    "pseudogene_calls_pfalNF54.json": "Plasmodium falciparum NF54",
    "pseudogene_calls_pfal3D7.json": "Plasmodium falciparum 3D7",
}


def genome_request(organism: str) -> tuple[str, WDKSearchConfig, JSONObject]:
    return (
        GENOME_SEARCH,
        WDKSearchConfig(parameters={"organism": json.dumps([organism])}),
        {
            "attributes": list(GENE_ATTRIBUTES),
            "tables": [],
            "pagination": {"offset": 0, "numRecords": GENOME_RECORDS},
        },
    )


def write_answers(into: Path, answers: Mapping[str, WDKAnswer]) -> None:
    into.mkdir(parents=True, exist_ok=True)
    for name, answer in answers.items():
        body = answer.model_dump(mode="json", by_alias=True)
        (into / name).write_text(json.dumps(body, separators=(",", ":")) + "\n")


async def record(into: Path) -> None:
    use_qa_sites()
    await act_as_the_test_account()
    client = get_wdk_client(SITE)
    answers: dict[str, WDKAnswer] = {}
    try:
        for name, organism in GENOMES.items():
            answers[name] = await client.run_search_report(
                "transcript", *genome_request(organism)
            )
    finally:
        await close_all_clients()
    write_answers(into, answers)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=FIXTURES)
    asyncio.run(record(parser.parse_args().out))

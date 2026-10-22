"""Record the reads that resolve a gene id the locus-tag search does not find, as the
gene id tests read them from a QA site.

Run it from the repository root as the test account (WDK_TEST_TOKEN, or
WDK_TEST_EMAIL and WDK_TEST_PASSWORD):
``uv run python scripts/record_audit_gene_ids.py [--out DIR]``.
"""

import argparse
import asyncio
from pathlib import Path

from pydantic import BaseModel, ConfigDict, JsonValue
from scripts.record_audit_fixtures import (
    FIXTURES,
    act_as_the_test_account,
    served_answers,
)
from veupathdb.devtools import use_qa_sites
from veupathdb.wdk import close_all_clients, get_wdk_client

from veupathdb_mcp.audit.gene_ids import (
    TEXT_SEARCH,
    matched_genes,
    text_answer,
    text_organisms,
)
from veupathdb_mcp.audit.genes import GENE_ATTRIBUTES, locus_tag_answers

SITE = "plasmodb"
GIVEN = "PfNF54_100037200"
BESIDE = "PF3D7_1032400"
FILE = "gene_ids_pfalNF54_piga.json"
SEARCH_PATH = f"/record-types/transcript/searches/{TEXT_SEARCH}"


class GeneIdRecording(BaseModel):
    model_config = ConfigDict(frozen=True)

    site: str
    given: str
    batch: list[JsonValue]
    search: JsonValue
    text: list[JsonValue]
    resolved: list[JsonValue]


async def _recording() -> GeneIdRecording:
    batch = await locus_tag_answers(SITE, [GIVEN, BESIDE], GENE_ATTRIBUTES)
    search = await get_wdk_client(SITE).get(SEARCH_PATH, {"expandParams": "true"})
    text = await text_answer(SITE, GIVEN, await text_organisms(SITE))
    matched = matched_genes(text, GIVEN)
    resolved = await locus_tag_answers(SITE, matched, GENE_ATTRIBUTES)
    return GeneIdRecording(
        site=SITE,
        given=GIVEN,
        batch=served_answers(batch),
        search=search,
        text=served_answers([text]),
        resolved=served_answers(resolved),
    )


def write_recording(into: Path, recorded: GeneIdRecording) -> None:
    into.mkdir(parents=True, exist_ok=True)
    (into / FILE).write_text(recorded.model_dump_json(indent=1) + "\n")


async def record(into: Path) -> None:
    use_qa_sites()
    await act_as_the_test_account()
    try:
        recorded = await _recording()
    finally:
        await close_all_clients()
    write_recording(into, recorded)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=FIXTURES)
    arguments = parser.parse_args()
    asyncio.run(record(arguments.out))

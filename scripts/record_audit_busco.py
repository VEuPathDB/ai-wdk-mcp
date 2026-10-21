"""Record the organism report the genome-priority audit tests read from QA sites.

Run it from the repository root as the test account (WDK_TEST_TOKEN, or
WDK_TEST_EMAIL and WDK_TEST_PASSWORD):
``uv run python -m scripts.record_audit_busco SITE [--out DIR]``.
"""

import argparse
import asyncio
from pathlib import Path

from pydantic import JsonValue
from scripts.record_audit_fixtures import FIXTURES, write_served
from veupathdb.devtools import use_qa_sites
from veupathdb.testing.wdk_credentials import act_as_the_test_account
from veupathdb.wdk import WDKAnswer, close_all_clients

from veupathdb_mcp.audit.busco import BUSCO_ATTRIBUTES
from veupathdb_mcp.audit.genes import organism_report

SITES = ("plasmodb", "toxodb")


def fixture_name(site: str) -> str:
    return f"busco_{site}.json"


def served_records(answer: WDKAnswer) -> list[JsonValue]:
    return [record.model_dump(mode="json", by_alias=True) for record in answer.records]


async def record(site: str, into: Path) -> None:
    use_qa_sites()
    await act_as_the_test_account()
    try:
        answer = await organism_report(site, BUSCO_ATTRIBUTES)
    finally:
        await close_all_clients()
    write_served(into, {fixture_name(site): served_records(answer)})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("site", choices=SITES)
    parser.add_argument("--out", type=Path, default=FIXTURES)
    arguments = parser.parse_args()
    asyncio.run(record(arguments.site, arguments.out))

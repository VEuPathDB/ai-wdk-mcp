"""Record one QA site's AllDatasets standard report as a test fixture.

The site comes from the QA list whatever the environment names, so no
recording reaches a production site. The report is an open path, so it travels
as the shared guest. Run it from the repository root:
``uv run python scripts/record_all_datasets.py plasmodb``.
"""

import asyncio
import sys
import time
from pathlib import Path

import httpx
from veupathdb.devtools import use_qa_sites
from veupathdb.devtools.wdk_capture import wdk_record
from veupathdb.guest_token import guest_tokens
from veupathdb.wdk import get_site_router

from veupathdb_mcp.catalog.catalog_metadata import (
    DATASET_REPORT_PATH,
    dataset_report_request,
)

_FIXTURES = Path(__file__).resolve().parent.parent / "tests/unit/catalog/fixtures"


async def record(site_id: str) -> Path:
    """Post the report the catalog build posts to the QA site, and write the exchange."""
    use_qa_sites()
    service = get_site_router().get_site(site_id).base_url
    url = service + DATASET_REPORT_PATH
    guest = await guest_tokens().token(service)
    started = time.perf_counter()
    async with httpx.AsyncClient(
        timeout=300, cookies={"Authorization": guest}
    ) as client:
        response = await client.post(url, json=dataset_report_request())
    response.raise_for_status()
    exchange = wdk_record(
        request=response.request,
        status=response.status_code,
        request_body=response.request.content,
        response_body=response.content,
        ms=(time.perf_counter() - started) * 1000.0,
    )
    _FIXTURES.mkdir(parents=True, exist_ok=True)
    path = _FIXTURES / f"{site_id}_all_datasets.json"
    path.write_text(exchange.model_dump_json(indent=1) + "\n")
    return path


if __name__ == "__main__":
    asyncio.run(record(sys.argv[1]))

import argparse
import asyncio
import json
import time
from pathlib import Path

import httpx
from veupathdb.devtools import WDKExchange, use_qa_sites, wdk_record
from veupathdb.testing import NO_CREDENTIALS_REASON, registered_wdk_token
from veupathdb.wdk import get_site_router

FIXTURES = Path(__file__).resolve().parent.parent / "tests/unit/catalog/fixtures"
FILE = "plasmodb_ngs_snps_summary_counts.json"
SITE = "plasmodb"
PATH = (
    "/record-types/transcript/searches/GenesByNgsSnps/"
    "variation_sample_meta/summary-counts"
)
BODY = {
    "filters": [],
    "contextParamValues": {
        "organismSinglePick": '["Plasmodium falciparum 3D7"]',
        "eda_sample_table_suffix": "s3be28bbe14_sample",
        "variation_sample_meta": '{"filters": []}',
    },
}


def write_exchange(into: Path, exchange: WDKExchange) -> Path:
    into.mkdir(parents=True, exist_ok=True)
    path = into / FILE
    path.write_text(exchange.model_dump_json(indent=1) + "\n")
    return path


async def record() -> WDKExchange:
    use_qa_sites()
    token = await registered_wdk_token()
    if token is None:
        raise RuntimeError(NO_CREDENTIALS_REASON)
    site = get_site_router().get_site(SITE)
    async with httpx.AsyncClient(
        timeout=120, cookies={"Authorization": token}
    ) as client:
        request = client.build_request(
            "POST",
            site.base_url + PATH,
            content=json.dumps(BODY),
            headers={"content-type": "application/json"},
        )
        started = time.perf_counter()
        response = await client.send(request)
    if response.status_code != httpx.codes.OK:
        msg = f"{SITE} answered {response.status_code} to {PATH}"
        raise RuntimeError(msg)
    return wdk_record(
        request=request,
        status=response.status_code,
        request_body=request.content,
        response_body=response.content,
        ms=(time.perf_counter() - started) * 1000.0,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=FIXTURES)
    write_exchange(parser.parse_args().out, asyncio.run(record()))

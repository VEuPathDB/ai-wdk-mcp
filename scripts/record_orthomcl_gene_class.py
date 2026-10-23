import argparse
import asyncio
import json
import time
from pathlib import Path

import httpx
from pydantic import BaseModel, ConfigDict
from veupathdb.devtools import WDKExchange, use_qa_sites, wdk_record
from veupathdb.testing import NO_CREDENTIALS_REASON, registered_wdk_token
from veupathdb.wdk import get_site_router

from veupathdb_mcp.catalog import GENE_RECORD_TYPE

FIXTURES = Path(__file__).resolve().parent.parent / "tests/unit/catalog/fixtures"
FILE = "orthomcl_gene_class.json"
SITE = "orthomcl"
GENE = "PF3D7_1133400"
RECORD_TYPES_PATH = "/record-types"


class GeneClassWire(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    site: str
    gene: str
    record_types: WDKExchange
    gene_record: WDKExchange


def gene_record_body(project_id: str) -> dict[str, object]:
    return {
        "primaryKey": [
            {"name": "source_id", "value": GENE},
            {"name": "project_id", "value": project_id},
        ],
        "attributes": [],
        "tables": [],
    }


def write_wire(into: Path, wire: GeneClassWire) -> Path:
    into.mkdir(parents=True, exist_ok=True)
    path = into / FILE
    path.write_text(wire.model_dump_json(indent=1) + "\n")
    return path


async def _exchange(client: httpx.AsyncClient, request: httpx.Request) -> WDKExchange:
    started = time.perf_counter()
    response = await client.send(request)
    return wdk_record(
        request=request,
        status=response.status_code,
        request_body=request.content,
        response_body=response.content,
        ms=(time.perf_counter() - started) * 1000.0,
    )


async def record(into: Path) -> Path:
    use_qa_sites()
    token = await registered_wdk_token()
    if token is None:
        raise RuntimeError(NO_CREDENTIALS_REASON)
    site = get_site_router().get_site(SITE)
    async with httpx.AsyncClient(
        timeout=120, cookies={"Authorization": token}
    ) as client:
        listed = await _exchange(
            client, client.build_request("GET", site.base_url + RECORD_TYPES_PATH)
        )
        read = await _exchange(
            client,
            client.build_request(
                "POST",
                f"{site.base_url}/record-types/{GENE_RECORD_TYPE}/records",
                content=json.dumps(gene_record_body(site.project_id)),
                headers={"content-type": "application/json"},
            ),
        )
    if listed.status != httpx.codes.OK:
        msg = f"{SITE} answered {listed.status} to {RECORD_TYPES_PATH}"
        raise RuntimeError(msg)
    wire = GeneClassWire(site=SITE, gene=GENE, record_types=listed, gene_record=read)
    return write_wire(into, wire)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=FIXTURES)
    asyncio.run(record(parser.parse_args().out))

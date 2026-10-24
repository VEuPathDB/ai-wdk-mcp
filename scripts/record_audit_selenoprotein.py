import argparse
import asyncio
import base64
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import NoReturn

import httpx
from scripts.record_audit_fixtures import FIXTURES, act_as_the_test_account
from scripts.record_audit_records import (
    REFUSED,
    RecordExchange,
    RecordingStoppedError,
    RecordWire,
    StoreExchange,
    Tally,
    read_wire,
    write,
)
from veupathdb import set_observer
from veupathdb.devtools import use_qa_sites
from veupathdb.errors import VEuPathDBError
from veupathdb.jbrowse import JBrowseClient
from veupathdb.wdk import (
    WDKRecordInstance,
    close_all_clients,
    get_site,
    get_strategy_api,
)

from veupathdb_mcp.audit import gene_ids, gene_models, genes, record_reads, served
from veupathdb_mcp.tools.audit_tools import audit_selenoprotein_end

SITE = "toxodb"
GENE = "TGGT1_316600"
REFERENCE = "TGME49_316600"
FILE = "selenoprotein_tgonGT1_selk.json"
RECORD_BUDGET = 7
STORE_BUDGET = 3

type RecordKey = tuple[
    str, tuple[tuple[str, str], ...], tuple[str, ...], tuple[str, ...]
]
type Send = Callable[..., Awaitable[WDKRecordInstance]]


def exchange_key(exchange: RecordExchange) -> RecordKey:
    return (
        exchange.record_type,
        tuple(sorted(exchange.primary_key.items())),
        tuple(exchange.attributes),
        tuple(exchange.tables),
    )


class RecordTape:
    def __init__(self, send: Send, held: list[RecordExchange], budget: int) -> None:
        self._send = send
        self._held = {exchange_key(e): e for e in held}
        self._budget = budget
        self.kept: list[RecordExchange] = []
        self.sent = 0

    async def _live(
        self,
        record_type: str,
        primary_key: list[dict[str, str]],
        attributes: list[str],
        tables: list[str],
    ) -> RecordExchange:
        if self.sent >= self._budget:
            msg = f"the recording spent its {self._budget} record reads"
            raise RecordingStoppedError(msg)
        self.sent += 1
        key = {part["name"]: part["value"] for part in primary_key}
        try:
            record = await self._send(
                record_type, primary_key, attributes=attributes, tables=tables
            )
            status, body = 200, record.model_dump(mode="json", by_alias=True)
        except VEuPathDBError as exc:
            status, body = exc.status, exc.detail
        print("record", record_type, key, attributes, tables, status)
        return RecordExchange(
            record_type=record_type,
            primary_key=key,
            attributes=attributes,
            tables=tables,
            status=status,
            body=body,
        )

    async def get_single_record(
        self,
        record_type: str,
        primary_key: list[dict[str, str]],
        *,
        attributes: list[str],
        tables: list[str],
    ) -> WDKRecordInstance:
        key = {part["name"]: part["value"] for part in primary_key}
        held = self._held.get(
            (record_type, tuple(sorted(key.items())), tuple(attributes), tuple(tables))
        )
        exchange = held or await self._live(
            record_type, primary_key, attributes, tables
        )
        self.kept.append(exchange)
        if exchange.status >= REFUSED:
            msg = f"the site answered {exchange.status} to the {record_type} {key}"
            raise RecordingStoppedError(msg)
        return WDKRecordInstance.model_validate(exchange.body)


class StoreTape(httpx.AsyncBaseTransport):
    def __init__(
        self,
        inner: httpx.AsyncBaseTransport,
        held: list[StoreExchange],
        budget: int,
    ) -> None:
        self._inner = inner
        self._held = {(e.url, e.byte_range): e for e in held}
        self._budget = budget
        self.kept: list[StoreExchange] = []
        self.sent = 0

    async def _live(self, request: httpx.Request) -> StoreExchange:
        if self.sent >= self._budget:
            msg = f"the recording spent its {self._budget} store reads"
            raise RecordingStoppedError(msg)
        self.sent += 1
        response = await self._inner.handle_async_request(request)
        body = await response.aread()
        print(
            "store", request.url, request.headers.get("Range", ""), response.status_code
        )
        return StoreExchange(
            url=str(request.url),
            byte_range=request.headers.get("Range", ""),
            status=response.status_code,
            body=base64.b64encode(body),
        )

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        held = self._held.get((str(request.url), request.headers.get("Range", "")))
        exchange = held or await self._live(request)
        self.kept.append(exchange)
        if exchange.status >= REFUSED:
            msg = f"the store answered {exchange.status} to {request.url}"
            raise RecordingStoppedError(msg)
        return httpx.Response(exchange.status, content=exchange.body, request=request)

    async def aclose(self) -> None:
        await self._inner.aclose()


def transcript_key(records: list[RecordExchange]) -> list[str]:
    return next(list(r.primary_key) for r in records if r.record_type == "transcript")


def _refused(*_: object) -> NoReturn:
    msg = "the check asked for a read the recording does not allow"
    raise RecordingStoppedError(msg)


def tape_the_reads(records: RecordTape, store: StoreTape) -> JBrowseClient:
    client = JBrowseClient(base_url=get_site(SITE).web_base_url, transport=store)
    gene_models.get_strategy_api = lambda site_id: records
    record_reads.get_strategy_api = lambda site_id: records
    served.get_jbrowse_client = lambda site_id: client
    gene_ids.genes_by_text = _refused
    genes.dataset_client = _refused
    return client


async def record(into: Path) -> None:
    use_qa_sites()
    await act_as_the_test_account()
    tally = Tally()
    set_observer(tally)
    held = read_wire(into / FILE) if (into / FILE).exists() else None
    records = RecordTape(
        get_strategy_api(SITE).get_single_record,
        held.records if held else [],
        RECORD_BUDGET,
    )
    store = StoreTape(
        httpx.AsyncHTTPTransport(), held.store if held else [], STORE_BUDGET
    )
    client = tape_the_reads(records, store)
    try:
        result = await audit_selenoprotein_end(SITE, GENE, REFERENCE)
        print("verdict", result.verdict)
    finally:
        await client.close()
        await close_all_clients()
        print("record reads sent", records.sent, "store reads sent", store.sent)
        print("wdk observed", len(tally.wdk), tally.wdk)
        print("store observed", len(tally.store), tally.store)
    write(
        into,
        FILE,
        RecordWire(
            site=SITE,
            transcript_key=transcript_key(records.kept),
            records=records.kept,
            store=store.kept,
        ),
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=FIXTURES)
    arguments = parser.parse_args()
    asyncio.run(record(arguments.out))

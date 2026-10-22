import base64

import httpx
import pytest
from scripts.record_audit_records import (
    RecordExchange,
    RecordingStoppedError,
    StoreExchange,
)
from scripts.record_audit_selenoprotein import (
    FILE,
    GENE,
    RECORD_BUDGET,
    REFERENCE,
    SITE,
    STORE_BUDGET,
    RecordTape,
    StoreTape,
    transcript_key,
)
from veupathdb.errors import WDKError
from veupathdb.wdk import WDKRecordInstance

KEY = [{"name": "source_id", "value": GENE}, {"name": "project_id", "value": "ToxoDB"}]


def body(gene: str) -> dict[str, object]:
    return {
        "displayName": "",
        "id": [{"name": "source_id", "value": gene}],
        "recordClassName": "",
        "attributes": {"organismAbbrev": "tgonGT1"},
        "tables": {},
        "tableErrors": [],
    }


def exchange(gene: str, status: int = 200) -> RecordExchange:
    return RecordExchange(
        record_type="gene",
        primary_key={"source_id": gene, "project_id": "ToxoDB"},
        attributes=["organismAbbrev"],
        tables=[],
        status=status,
        body=body(gene),
    )


class Inner:
    def __init__(self, refusal: int | None = None) -> None:
        self.calls: list[str] = []
        self._refusal = refusal

    async def get_single_record(
        self,
        record_type: str,
        primary_key: list[dict[str, str]],
        *,
        attributes: list[str],
        tables: list[str],
    ) -> WDKRecordInstance:
        gene = primary_key[0]["value"]
        self.calls.append(gene)
        if self._refusal is not None:
            msg = f"{gene} is refused"
            raise WDKError(msg, status=self._refusal)
        return WDKRecordInstance.model_validate(body(gene))


def test_the_recording_reads_gt1_selk_against_me49_on_toxodb() -> None:
    assert (SITE, GENE, REFERENCE, FILE) == (
        "toxodb",
        "TGGT1_316600",
        "TGME49_316600",
        "selenoprotein_tgonGT1_selk.json",
    )
    assert (RECORD_BUDGET, STORE_BUDGET) == (7, 3)


async def test_a_read_the_wire_holds_is_served_and_not_sent() -> None:
    inner = Inner()
    tape = RecordTape(inner.get_single_record, [exchange(GENE)], 0)

    record = await tape.get_single_record(
        "gene", KEY, attributes=["organismAbbrev"], tables=[]
    )

    assert record.attributes == {"organismAbbrev": "tgonGT1"}
    assert (inner.calls, tape.sent, tape.kept) == ([], 0, [exchange(GENE)])


async def test_a_read_the_wire_lacks_is_sent_and_kept() -> None:
    inner = Inner()
    tape = RecordTape(inner.get_single_record, [], 1)

    await tape.get_single_record("gene", KEY, attributes=["organismAbbrev"], tables=[])

    assert (inner.calls, tape.sent) == ([GENE], 1)
    assert tape.kept == [exchange(GENE)]


async def test_a_read_past_the_budget_stops_the_recording_unsent() -> None:
    inner = Inner()
    tape = RecordTape(inner.get_single_record, [], 0)

    with pytest.raises(RecordingStoppedError, match="spent its 0 record reads"):
        await tape.get_single_record("gene", KEY, attributes=[], tables=[])

    assert (inner.calls, tape.kept) == ([], [])


async def test_a_refused_read_is_kept_with_its_status_and_stops_the_recording() -> None:
    inner = Inner(refusal=404)
    tape = RecordTape(inner.get_single_record, [], 5)

    with pytest.raises(RecordingStoppedError, match="answered 404"):
        await tape.get_single_record(
            "gene", KEY, attributes=["organismAbbrev"], tables=[]
        )

    assert [(e.status, e.body) for e in tape.kept] == [(404, f"{GENE} is refused")]


def store_exchange(status: int = 206) -> StoreExchange:
    return StoreExchange(
        url="https://qa.toxodb.org/a/service/jbrowse/store?data=g.fa",
        byte_range="bytes=1-3",
        status=status,
        body=base64.b64encode(b"ACG"),
    )


async def read(tape: StoreTape) -> httpx.Response:
    async with httpx.AsyncClient(transport=tape) as client:
        return await client.get(
            "https://qa.toxodb.org/a/service/jbrowse/store",
            params={"data": "g.fa"},
            headers={"Range": "bytes=1-3"},
        )


async def test_a_store_read_the_wire_holds_is_served_and_not_sent() -> None:
    sent: list[str] = []
    inner = httpx.MockTransport(
        lambda r: sent.append(str(r.url)) or httpx.Response(500)
    )
    tape = StoreTape(inner, [store_exchange()], 0)

    response = await read(tape)

    assert (response.status_code, response.content) == (206, b"ACG")
    assert (sent, tape.sent, tape.kept) == ([], 0, [store_exchange()])


async def test_a_store_read_the_wire_lacks_is_sent_and_kept() -> None:
    tape = StoreTape(
        httpx.MockTransport(lambda r: httpx.Response(206, content=b"ACG")), [], 1
    )

    await read(tape)

    assert (tape.sent, tape.kept) == (1, [store_exchange()])


async def test_a_refused_store_read_stops_the_recording() -> None:
    tape = StoreTape(httpx.MockTransport(lambda r: httpx.Response(404)), [], 1)

    with pytest.raises(RecordingStoppedError, match="answered 404"):
        await read(tape)

    assert [e.status for e in tape.kept] == [404]


async def test_a_store_read_past_the_budget_stops_the_recording_unsent() -> None:
    tape = StoreTape(httpx.MockTransport(lambda r: httpx.Response(206)), [], 0)

    with pytest.raises(RecordingStoppedError, match="spent its 0 store reads"):
        await read(tape)

    assert tape.kept == []


def test_the_transcript_key_is_the_one_the_transcript_read_named() -> None:
    transcript = RecordExchange(
        record_type="transcript",
        primary_key={"gene_source_id": GENE, "source_id": "T", "project_id": "ToxoDB"},
        attributes=["protein_sequence"],
        tables=[],
        status=200,
        body=body(GENE),
    )

    assert transcript_key([exchange(GENE), transcript]) == [
        "gene_source_id",
        "source_id",
        "project_id",
    ]

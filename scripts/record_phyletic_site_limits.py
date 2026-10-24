import argparse
import asyncio
import time
from collections.abc import Awaitable, Callable
from pathlib import Path

import httpx
from pydantic import BaseModel, ConfigDict
from scripts.record_audit_fixtures import act_as_the_test_account
from veupathdb.devtools import use_qa_sites
from veupathdb.domain.parameters import (
    PHYLETIC_EXPRESSION_PARAM,
    PHYLETIC_EXPRESSION_SEARCH,
    PhyleticTree,
)
from veupathdb.testing import NO_CREDENTIALS_REASON, registered_wdk_token
from veupathdb.wdk import WDKAnswer, get_site_router

from veupathdb_mcp.catalog import (
    MAX_EXPRESSION_TERMS,
    MAX_EXPRESSION_WORK,
    ortho_taxonomy,
)

SITE = "orthomcl"
FILE = "orthomcl_phyletic_site_limits.json"
DATA = Path(__file__).resolve().parent.parent / "src/veupathdb_mcp/catalog/data"
MAX_READS = 30
MAX_SECONDS = 300.0
LADDER_TERMS = (250, 500, 1000, MAX_EXPRESSION_TERMS)
WIDE_TERMS = 250
WIDE_CODES = (8, 32, 128)
REPORT_PATH = (
    f"/record-types/group/searches/{PHYLETIC_EXPRESSION_SEARCH}/reports/standard"
)
COUNT_ONLY = {
    "attributes": ["primary_key"],
    "pagination": {"offset": 0, "numRecords": 0},
}


class Planned(BaseModel):
    model_config = ConfigDict(frozen=True)

    series: str
    terms: int
    expression: str


class Answered(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: int
    total: int | None = None
    error: str = ""


class Measured(BaseModel):
    model_config = ConfigDict(frozen=True)

    series: str
    terms: int
    characters: int
    status: int
    seconds: float
    total: int | None
    error: str


class LimitsRecording(BaseModel):
    model_config = ConfigDict(frozen=True)

    site: str
    search: str
    left: str
    right: str
    measured: tuple[Measured, ...]
    stopped: str


type Send = Callable[[str, float], Awaitable[Answered]]


def ladder(left: str, right: str, terms: int) -> str:
    return " OR ".join(f"{right}={k} AND {left}>={k + 1}" for k in range(terms))


def plan(tree: PhyleticTree, left: str, right: str) -> list[Planned]:
    genomes = sorted(tree.genomes_under([root.code for root in tree.roots]) - {right})
    planned = [
        Planned(series="ladder", terms=terms, expression=ladder(left, right, terms))
        for terms in LADDER_TERMS
    ]
    for width in dict.fromkeys(min(width, len(genomes)) for width in WIDE_CODES):
        unit = "+".join(genomes[:width])
        planned.append(
            Planned(
                series=f"wide-{width}",
                terms=WIDE_TERMS,
                expression=" OR ".join(
                    f"{right}={k} AND {unit}>={k + 1}" for k in range(WIDE_TERMS)
                ),
            )
        )
    return [
        step
        for step in planned
        if step.terms <= MAX_EXPRESSION_TERMS
        and step.terms * len(step.expression) <= MAX_EXPRESSION_WORK
    ]


async def measure(
    planned: list[Planned], send: Send, clock: Callable[[], float]
) -> tuple[list[Measured], str]:
    started = clock()
    measured: list[Measured] = []
    for step in planned[:MAX_READS]:
        remaining = MAX_SECONDS - (clock() - started)
        if remaining <= 0:
            return measured, "budget"
        sent = clock()
        answered = await send(step.expression, remaining)
        measured.append(
            Measured(
                series=step.series,
                terms=step.terms,
                characters=len(step.expression),
                status=answered.status,
                seconds=round(clock() - sent, 3),
                total=answered.total,
                error=answered.error,
            )
        )
        if answered.status != httpx.codes.OK:
            return measured, f"status {answered.status}"
    return measured, "plan"


def site_send(client: httpx.AsyncClient, url: str) -> Send:
    async def send(expression: str, remaining: float) -> Answered:
        body = {
            "searchConfig": {"parameters": {PHYLETIC_EXPRESSION_PARAM: expression}},
            "reportConfig": COUNT_ONLY,
        }
        try:
            response = await client.post(url, json=body, timeout=remaining)
        except httpx.TimeoutException:
            return Answered(status=0, error="timeout")
        if response.status_code != httpx.codes.OK:
            return Answered(status=response.status_code, error=response.text[:2000])
        answer = WDKAnswer.model_validate(response.json())
        return Answered(
            status=response.status_code, total=answer.meta.records_returned()
        )

    return send


async def record(into: Path, left: str, right: str) -> Path:
    use_qa_sites()
    await act_as_the_test_account()
    token = await registered_wdk_token()
    if token is None:
        raise RuntimeError(NO_CREDENTIALS_REASON)
    tree = await ortho_taxonomy(SITE)
    if tree is None:
        msg = f"{SITE} served no taxonomy"
        raise RuntimeError(msg)
    base = get_site_router().get_site(SITE).base_url
    async with httpx.AsyncClient(cookies={"Authorization": token}) as client:
        measured, stopped = await measure(
            plan(tree, left, right),
            site_send(client, base + REPORT_PATH),
            time.perf_counter,
        )
    recording = LimitsRecording(
        site=SITE,
        search=PHYLETIC_EXPRESSION_SEARCH,
        left=left,
        right=right,
        measured=tuple(measured),
        stopped=stopped,
    )
    return write_recording(into, recording)


def write_recording(into: Path, recording: LimitsRecording) -> Path:
    into.mkdir(parents=True, exist_ok=True)
    path = into / FILE
    path.write_text(recording.model_dump_json(indent=1) + "\n")
    return path


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=DATA)
    parser.add_argument("--left", default="tgon")
    parser.add_argument("--right", default="pfal")
    arguments = parser.parse_args()
    asyncio.run(record(arguments.out, arguments.left, arguments.right))

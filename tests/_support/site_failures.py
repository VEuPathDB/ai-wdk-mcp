from collections.abc import Awaitable, Callable

import httpx
from veupathdb.auth_context import veupathdb_auth_token_ctx
from veupathdb.errors import VEuPathDBError
from veupathdb.jbrowse import JBrowseClient
from veupathdb.wdk import VEuPathDBClient

SERVICE = "https://qa.plasmodb.org/plasmo.qa/service"
WEB = "https://qa.plasmodb.org/plasmo.qa"

type Handler = Callable[[httpx.Request], httpx.Response]


def answering(status: int) -> Handler:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, text="down", request=request)

    return handler


def silent(request: httpx.Request) -> httpx.Response:
    msg = "timed out"
    raise httpx.ConnectTimeout(msg, request=request)


async def wdk_read(handler: Handler) -> None:
    client = VEuPathDBClient(base_url=SERVICE, transport=httpx.MockTransport(handler))
    reset = veupathdb_auth_token_ctx.set("registered-token")
    try:
        await client.get("/record-types/transcript/searches/GenesByText", attempts=1)
    finally:
        veupathdb_auth_token_ctx.reset(reset)
        await client.close()


async def jbrowse_read(handler: Handler) -> None:
    client = JBrowseClient(base_url=WEB, transport=httpx.MockTransport(handler))
    reset = veupathdb_auth_token_ctx.set("registered-token")
    try:
        await client.track_list("rnaseqJunctions", "pfal3D7")
    finally:
        veupathdb_auth_token_ctx.reset(reset)
        await client.close()


async def raised(read: Awaitable[None]) -> VEuPathDBError | httpx.HTTPError:
    try:
        await read
    except (VEuPathDBError, httpx.HTTPError) as exc:
        return exc
    msg = "the read answered"
    raise AssertionError(msg)

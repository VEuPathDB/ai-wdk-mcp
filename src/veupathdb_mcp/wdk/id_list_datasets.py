from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from veupathdb.auth_context import veupathdb_auth_token_ctx
from veupathdb.errors import WDKLoginRequiredError
from veupathdb.wdk import VEuPathDBClient, get_site_router

TRANSCRIPTS_PER_GENE = 8


@asynccontextmanager
async def dataset_client(site_id: str) -> AsyncIterator[VEuPathDBClient]:
    if not veupathdb_auth_token_ctx.get():
        raise WDKLoginRequiredError
    router = get_site_router()
    site = router.get_site(site_id)
    routing = router._config.routing
    timeout = float(
        routing.portal_timeout if site.is_portal else routing.component_timeout
    )
    client = VEuPathDBClient(base_url=site.service_url, timeout=timeout)
    try:
        yield client
    finally:
        await client.close()

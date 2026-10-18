"""The registered account the live lane acts as."""

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
from veupathdb.auth_context import veupathdb_auth_token_ctx
from veupathdb.testing import NO_CREDENTIALS_REASON, registered_wdk_token


@pytest.fixture(autouse=True)
async def wdk_identity() -> AsyncGenerator[str]:
    """Act on WDK as the registered account for the length of every check."""
    token = await registered_wdk_token()
    if token is None:
        pytest.skip(NO_CREDENTIALS_REASON)
    reset = veupathdb_auth_token_ctx.set(token)
    yield token
    veupathdb_auth_token_ctx.reset(reset)

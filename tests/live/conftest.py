"""The registered account the live lane acts as."""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator

import pytest
from veupathdb.auth_context import veupathdb_auth_token_ctx
from veupathdb.wdk import password_login

_NO_CREDENTIALS = "WDK_TEST_EMAIL and WDK_TEST_PASSWORD name the account this lane uses"


@pytest.fixture
async def wdk_identity() -> AsyncGenerator[str]:
    """Act on WDK as the registered account for the length of one check."""
    email = os.environ.get("WDK_TEST_EMAIL", "")
    password = os.environ.get("WDK_TEST_PASSWORD", "")
    if not email or not password:
        pytest.skip(_NO_CREDENTIALS)
    token = await password_login("plasmodb", email, password)
    if token is None:
        pytest.fail("the site refused the account named by WDK_TEST_EMAIL")
    reset = veupathdb_auth_token_ctx.set(token)
    yield token
    veupathdb_auth_token_ctx.reset(reset)

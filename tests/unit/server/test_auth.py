"""What an inbound veupathdb-wdk-mcp credential proves, and the WDK identity it grants."""

from __future__ import annotations

from collections.abc import Iterator
from http import HTTPStatus

import pytest
import structlog.testing
from veupathdb.auth_context import veupathdb_auth_token_ctx
from veupathdb.errors import ExternalServiceError
from veupathdb.wdk.auth_login import VEuPathDBClaims

from veupathdb_mcp import identity
from veupathdb_mcp.auth import (
    CredentialMode,
    McpCredential,
    VEuPathDBTokenVerifier,
    wdk_identity,
)

SERVICE_SECRET = "wdk-mcp-service-secret-0123456789ab"
USER_TOKEN = "a-registered-veupathdb-bearer-token"
GUEST_TOKEN = "a-guest-veupathdb-bearer-token"
SUBJECT = "researcher@example.org"
_NO_SESSION = "the MCP auth path opened a database session"


@pytest.fixture
def mcp_credentials(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("PATHFINDER_MCP_SERVICE_TOKENS", f"gene-page:{SERVICE_SECRET}")
    identity._subjects.clear()
    yield
    identity._subjects.clear()


def _stub_claims(
    monkeypatch: pytest.MonkeyPatch, answer: VEuPathDBClaims | None | Exception
) -> list[str]:
    """Answer the JWKS verification without reaching the OAuth server."""
    verified: list[str] = []

    async def validate(token: str, oauth_url: str) -> VEuPathDBClaims | None:
        del oauth_url
        verified.append(token)
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(identity, "validate_oauth_token", validate)
    return verified


async def test_a_missing_credential_verifies_as_nothing(mcp_credentials: None) -> None:
    del mcp_credentials

    assert await VEuPathDBTokenVerifier().verify_token("") is None
    assert await VEuPathDBTokenVerifier().verify_token("   ") is None


async def test_the_service_secret_verifies_as_the_application(
    mcp_credentials: None,
) -> None:
    del mcp_credentials

    credential = await VEuPathDBTokenVerifier().verify_token(SERVICE_SECRET)

    assert credential is not None
    assert credential.mode is CredentialMode.SERVICE
    assert credential.client_id == "gene-page"


async def test_a_registered_bearer_verifies_as_the_oauth_subject(
    mcp_credentials: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    del mcp_credentials
    _stub_claims(monkeypatch, VEuPathDBClaims(sub=SUBJECT, is_guest=False))

    credential = await VEuPathDBTokenVerifier().verify_token(USER_TOKEN)

    assert credential is not None
    assert credential.mode is CredentialMode.VEUPATHDB_USER
    assert credential.client_id == SUBJECT
    assert credential.token == USER_TOKEN


async def test_the_verified_subject_is_remembered_for_the_next_call(
    mcp_credentials: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A bearer client does not pay a signature check on every call."""
    del mcp_credentials
    verified = _stub_claims(monkeypatch, VEuPathDBClaims(sub=SUBJECT, is_guest=False))

    await VEuPathDBTokenVerifier().verify_token(USER_TOKEN)
    await VEuPathDBTokenVerifier().verify_token(USER_TOKEN)

    assert verified == [USER_TOKEN]


async def test_the_user_path_opens_no_database_session(
    mcp_credentials: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The server keeps no account, so it reads no table to admit a caller."""
    del mcp_credentials
    _stub_claims(monkeypatch, VEuPathDBClaims(sub=SUBJECT, is_guest=False))

    def _refuse_a_session() -> object:
        raise AssertionError(_NO_SESSION)

    monkeypatch.setattr(
        "veupathdb_mcp.embeddings.db.embedding_session", _refuse_a_session
    )

    credential = await VEuPathDBTokenVerifier().verify_token(USER_TOKEN)

    assert credential is not None
    assert credential.client_id == SUBJECT


async def test_a_guest_bearer_verifies_as_nothing(
    mcp_credentials: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    del mcp_credentials
    _stub_claims(monkeypatch, VEuPathDBClaims(sub=SUBJECT, is_guest=True))

    assert await VEuPathDBTokenVerifier().verify_token(GUEST_TOKEN) is None


async def test_an_unsigned_bearer_verifies_as_nothing(
    mcp_credentials: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    del mcp_credentials
    verified = _stub_claims(monkeypatch, None)

    assert await VEuPathDBTokenVerifier().verify_token(USER_TOKEN) is None
    assert verified == [USER_TOKEN]


async def test_an_unreadable_signing_key_is_not_a_refusal(
    mcp_credentials: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A JWKS that cannot be read is 503 naming the provider, never a bad token."""
    del mcp_credentials
    _stub_claims(
        monkeypatch,
        ExternalServiceError(
            service="VEuPathDB identity provider",
            detail="the identity provider cannot be read",
            status=HTTPStatus.SERVICE_UNAVAILABLE,
        ),
    )

    with pytest.raises(ExternalServiceError):
        await VEuPathDBTokenVerifier().verify_token(USER_TOKEN)


def test_the_user_mode_acts_on_wdk_as_the_user() -> None:
    credential = McpCredential(
        token=USER_TOKEN,
        client_id=SUBJECT,
        scopes=[],
        mode=CredentialMode.VEUPATHDB_USER,
    )

    with wdk_identity(credential):
        assert veupathdb_auth_token_ctx.get() == USER_TOKEN

    assert veupathdb_auth_token_ctx.get() is None


def test_the_service_mode_leaves_the_wdk_request_token_empty() -> None:
    """The transport guard refuses a call under /users/ without a request token."""
    credential = McpCredential(
        token=SERVICE_SECRET,
        client_id="gene-page",
        scopes=[],
        mode=CredentialMode.SERVICE,
    )

    with wdk_identity(credential):
        assert veupathdb_auth_token_ctx.get() is None


async def test_a_refusal_names_the_mode_and_never_the_credential(
    mcp_credentials: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    del mcp_credentials
    _stub_claims(monkeypatch, None)
    verifier = VEuPathDBTokenVerifier()

    with structlog.testing.capture_logs() as events:
        await verifier.verify_token("")
        await verifier.verify_token(USER_TOKEN)
        await verifier.verify_token(SERVICE_SECRET)

    modes = [event.get("credential_mode") for event in events]
    assert modes == [CredentialMode.NONE.value, CredentialMode.VEUPATHDB_USER.value]
    logged = repr(events)
    assert USER_TOKEN not in logged
    assert SERVICE_SECRET not in logged


def test_the_credential_never_prints_its_token() -> None:
    credential = McpCredential(
        token=USER_TOKEN,
        client_id="pathfinder",
        scopes=[],
        mode=CredentialMode.VEUPATHDB_USER,
    )

    assert USER_TOKEN not in repr(credential)

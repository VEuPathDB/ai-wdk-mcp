"""Who a veupathdb-wdk-mcp call acts as, and the WDK identity that credential grants."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from enum import StrEnum

from mcp.server.auth.provider import AccessToken
from pydantic import ConfigDict, Field
from veupathdb import get_logger
from veupathdb.auth_context import veupathdb_auth_token_ctx

from veupathdb_mcp.identity import resolve_oauth_subject
from veupathdb_mcp.settings import get_mcp_settings

logger = get_logger(__name__)

__all__ = [
    "CredentialMode",
    "McpCredential",
    "VEuPathDBTokenVerifier",
    "wdk_identity",
]

_NO_REGISTERED_USER = "the bearer names no registered VEuPathDB user"


class CredentialMode(StrEnum):
    """The credential a call carries, in the admission record's vocabulary."""

    NONE = "none"
    SERVICE = "service"
    VEUPATHDB_USER = "veupathdb_user"


class McpCredential(AccessToken):
    """What a verified credential proves.

    ``client_id`` names the application in service mode and the VEuPathDB
    subject in user mode. This server keeps no account of its own.
    """

    model_config = ConfigDict(frozen=True)

    token: str = Field(repr=False)
    mode: CredentialMode


def _refuse(mode: CredentialMode, reason: str) -> None:
    """Report a refused call by mode. The credential itself never reaches a log."""
    logger.info("Refused an MCP call", credential_mode=mode.value, reason=reason)


class VEuPathDBTokenVerifier:
    """Verifies an inbound bearer against the applications, then against VEuPathDB.

    A user bearer is verified against the OAuth signing key alone, so the
    server opens no database and reads no account.
    """

    async def verify_token(self, token: str) -> McpCredential | None:
        """Verify a bearer. None refuses the call, and the transport answers 401."""
        presented = token.strip()
        if not presented:
            _refuse(CredentialMode.NONE, "the call carried no credential")
            return None

        registry = get_mcp_settings().mcp_service_tokens
        application_id = registry.application_for(presented)
        if application_id is not None:
            return McpCredential(
                token=presented,
                client_id=application_id,
                scopes=[],
                mode=CredentialMode.SERVICE,
            )

        subject = await resolve_oauth_subject(presented)
        if subject is None:
            _refuse(CredentialMode.VEUPATHDB_USER, _NO_REGISTERED_USER)
            return None
        return McpCredential(
            token=presented,
            client_id=subject,
            scopes=[],
            mode=CredentialMode.VEUPATHDB_USER,
        )


@contextmanager
def wdk_identity(credential: McpCredential) -> Iterator[None]:
    """Act on WDK as the credential names.

    Only a user credential travels. A service credential leaves the request token
    empty, so the transport guard refuses a call under ``/users/``.
    """
    acts_as_user = credential.mode is CredentialMode.VEUPATHDB_USER
    reset = veupathdb_auth_token_ctx.set(credential.token if acts_as_user else None)
    try:
        yield
    finally:
        veupathdb_auth_token_ctx.reset(reset)

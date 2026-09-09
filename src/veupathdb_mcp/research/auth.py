"""Who a research call acts as. One credential mode: a configured application."""

from __future__ import annotations

from mcp.server.auth.provider import AccessToken
from pydantic import ConfigDict, Field
from veupathdb.logging import get_logger

from veupathdb_mcp.research.settings import get_research_settings

logger = get_logger(__name__)

_NO_CREDENTIAL = "the call carried no credential"
_UNKNOWN_APPLICATION = "the bearer names no configured application"


class ResearchCredential(AccessToken):
    """The application a verified secret proves. No user identity travels."""

    model_config = ConfigDict(frozen=True)

    token: str = Field(repr=False)


class ServiceTokenVerifier:
    """Verifies an inbound bearer against the configured applications.

    The server reaches open-web APIs on its own account, so a caller proves an
    application and never a person.
    """

    async def verify_token(self, token: str) -> ResearchCredential | None:
        """Verify a bearer. None refuses the call, and the transport answers 401."""
        presented = token.strip()
        if not presented:
            logger.info("Refused a research call", reason=_NO_CREDENTIAL)
            return None

        registry = get_research_settings().research_service_tokens
        application_id = registry.application_for(presented)
        if application_id is None:
            logger.info("Refused a research call", reason=_UNKNOWN_APPLICATION)
            return None
        return ResearchCredential(
            token=presented,
            client_id=application_id,
            scopes=[],
        )

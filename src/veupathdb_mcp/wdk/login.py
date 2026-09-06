"""Opening and ending a VEuPathDB session with an email and a password."""

from veupathdb.logging import get_logger
from veupathdb.wdk.auth_login import password_login, password_logout

logger = get_logger(__name__)


async def start_veupathdb_session(
    site_id: str,
    *,
    email: str,
    password: str,
    redirect_url: str,
) -> str | None:
    """The WDK token of the account, or None when the site refused it."""
    return await password_login(site_id, email, password, redirect_url=redirect_url)


async def end_veupathdb_session(site_id: str, veupathdb_token: str | None) -> bool:
    """Ask WDK to end the session the token belongs to.

    WDK logs out whoever made the request, and answers an uncredentialed one as
    a guest, so a logout without the token ends nobody's session.
    """
    if not veupathdb_token:
        return False
    ended: bool = await password_logout(site_id, veupathdb_token)
    if not ended:
        logger.warning("VEuPathDB did not end the session", site_id=site_id)
    return ended

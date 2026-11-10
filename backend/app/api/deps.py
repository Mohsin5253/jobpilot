from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import User
from app.security import COOKIE_NAME, decode_token

SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def current_user(request: Request, session: SessionDep) -> User:
    token = request.cookies.get(COOKIE_NAME)
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        token = auth[7:]
    decoded = decode_token(token) if token else None
    user = await session.get(User, decoded[0]) if decoded else None
    now = datetime.now(UTC)
    # A changed password or "sign out everywhere" bumps token_version, which ends every older session.
    if user is None or decoded[1] != user.token_version or (user.expires_at and user.expires_at < now):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated", headers={"WWW-Authenticate": "Bearer"})
    # Active users drive what the shared ingester fetches; recorded at most hourly to keep reads read-only.
    if not user.last_seen_at or now - user.last_seen_at > timedelta(hours=1):
        user.last_seen_at = now
        await session.commit()
    return user


async def real_user(user: Annotated[User, Depends(current_user)]) -> User:
    """Account and mail settings are off limits to throwaway demo accounts."""
    if user.is_demo:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This is a demo account. Sign up to use this feature.")
    return user


async def admin_user(user: Annotated[User, Depends(current_user)]) -> User:
    from app.config import settings

    if not (user.is_admin or user.email.lower() in {e.lower() for e in settings.admin_emails}):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admins only")
    return user


async def extension_user(request: Request, session: SessionDep) -> User:
    """Personal tokens ("jpx_...") from the Chrome extension; valid only on /api/extension routes."""
    from sqlalchemy import select

    from app.models import ApiToken
    from app.security import hash_reset_token

    auth = request.headers.get("authorization", "")
    token = auth[7:] if auth.lower().startswith("bearer ") else ""
    if not token.startswith("jpx_"):
        return await current_user(request, session)  # the web app itself may call these too
    row = (await session.execute(select(ApiToken).where(ApiToken.token_hash == hash_reset_token(token)))).scalar_one_or_none()
    user = await session.get(User, row.user_id) if row else None
    if user is None or user.is_demo:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or revoked extension token")
    now = datetime.now(UTC)
    if not row.last_used_at or now - row.last_used_at > timedelta(minutes=10):
        row.last_used_at = now
        await session.commit()
    return user


UserDep = Annotated[User, Depends(current_user)]
ExtensionUserDep = Annotated[User, Depends(extension_user)]
RealUserDep = Annotated[User, Depends(real_user)]
AdminDep = Annotated[User, Depends(admin_user)]

"""Sign in / sign up with Google (OpenID Connect: openid, email, profile only; no Gmail access).

Reuses the Google OAuth client set up for Gmail sending. The round trip is protected by a signed `state` bound to a
short-lived browser cookie (so a callback can't be replayed in another browser). Signing up with Google still needs
the same two confirmations as the form (18 or older, and the privacy notice), which the register page sends along.
An existing account with the same verified email is linked to the Google account on first use.
"""

import hashlib
import hmac
import json
import secrets
import time
from base64 import urlsafe_b64decode, urlsafe_b64encode
from datetime import UTC, datetime
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select

from app.api.deps import SessionDep
from app.api.routes.auth import _issue
from app.config import settings
from app.logging import log
from app.models import Profile, User
from app.schemas import Preferences
from app.security import hash_password
from app.services import gmail
from app.services.consent import grant
from app.services.ratelimit import client_ip, hit
from app.safety import egress

router = APIRouter(prefix="/auth", tags=["auth"])
STATE_COOKIE = "jp_g_state"
STATE_TTL_S = 600


def redirect_uri() -> str:
    return f"{settings.app_url.rstrip('/')}/api/auth/google/callback"


def _sign(payload: bytes) -> str:
    return hmac.new(f"google-signin:{settings.jwt_secret}".encode(), payload, hashlib.sha256).hexdigest()[:32]


def make_state(data: dict) -> str:
    raw = urlsafe_b64encode(json.dumps({**data, "exp": int(time.time()) + STATE_TTL_S}, separators=(",", ":")).encode()).decode().rstrip("=")
    return f"{raw}.{_sign(raw.encode())}"


def read_state(state: str) -> dict | None:
    raw, _, sig = state.partition(".")
    if not raw or not hmac.compare_digest(sig, _sign(raw.encode())):
        return None
    data = json.loads(urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
    return data if data.get("exp", 0) >= time.time() else None


def _safe_next(path: str | None, default: str) -> str:
    return path if path and path.startswith("/") and not path.startswith("//") else default


def _back(page: str, code: str) -> RedirectResponse:
    r = RedirectResponse(f"{settings.app_url.rstrip('/')}/{page}?google={code}", status_code=303)
    r.delete_cookie(STATE_COOKIE, path="/")
    return r


@router.get("/providers")
async def providers() -> dict:
    return {"google": settings.google_mail_enabled}


@router.get("/google/start")
async def google_start(request: Request, mode: str = "login", adult: int = 0, consent: int = 0, next: str = "") -> RedirectResponse:
    if not settings.google_mail_enabled:
        raise HTTPException(404, "Sign in with Google isn't set up on this server")
    await hit("login", client_ip(request))
    if mode == "register" and not (adult and consent):
        return _back("register", "confirm")
    nonce = secrets.token_urlsafe(16)
    state = make_state({"m": "register" if mode == "register" else "login", "a": int(bool(adult)), "c": int(bool(consent)), "n": hashlib.sha256(nonce.encode()).hexdigest()[:24], "next": _safe_next(next, "")})
    params = {
        "client_id": settings.google_client_id, "redirect_uri": redirect_uri(), "response_type": "code", "scope": "openid email profile",
        "state": state, "prompt": "select_account", "access_type": "online",
    }
    r = RedirectResponse(f"{gmail.AUTH_URL}?{urlencode(params)}", status_code=303)
    r.set_cookie(STATE_COOKIE, nonce, max_age=STATE_TTL_S, httponly=True, secure=settings.cookie_secure, samesite="lax", path="/")
    return r


async def _identity(code: str) -> dict:
    async with egress.client("gmail", timeout=20) as c:
        tok = await c.post(gmail.TOKEN_URL, data={"code": code, "client_id": settings.google_client_id, "client_secret": settings.google_client_secret, "redirect_uri": redirect_uri(), "grant_type": "authorization_code"})
        if tok.status_code != 200:
            raise gmail.GmailError("token")
        info = await c.get(gmail.USERINFO_URL, headers={"authorization": f"Bearer {tok.json()['access_token']}"})
        if info.status_code != 200:
            raise gmail.GmailError("userinfo")
        return info.json()


@router.get("/google/callback")
async def google_callback(request: Request, session: SessionDep, code: str = "", state: str = "", error: str = "") -> RedirectResponse:
    data = read_state(state) if state else None
    page = "register" if (data or {}).get("m") == "register" else "login"
    if error or not code:
        return _back(page, "cancelled")
    nonce = request.cookies.get(STATE_COOKIE, "")
    if data is None or not nonce or not hmac.compare_digest(data["n"], hashlib.sha256(nonce.encode()).hexdigest()[:24]):
        return _back(page, "expired")
    try:
        who = await _identity(code)
    except (gmail.GmailError, httpx.HTTPError, KeyError):
        log.warning("google_signin.failed")
        return _back(page, "failed")
    sub, email = str(who.get("sub") or ""), str(who.get("email") or "").lower()
    if not sub or not email or not who.get("email_verified"):
        return _back(page, "unverified")

    user = (await session.execute(select(User).where(User.google_sub == sub))).scalar_one_or_none()
    if user is None:
        user = (await session.execute(select(User).where(func.lower(User.email) == email, User.is_demo.is_(False)))).scalar_one_or_none()
        if user is not None:
            user.google_sub = sub  # same verified email: link the Google account to it
    created = False
    if user is None:
        if data["m"] != "register" or not (data["a"] and data["c"]):
            return _back("register", "no_account")
        now = datetime.now(UTC)
        user = User(
            email=email, name=str(who.get("name") or "")[:200], password_hash=hash_password(secrets.token_urlsafe(32)), google_sub=sub,
            is_admin=email in {e.lower() for e in settings.admin_emails}, adult_confirmed_at=now,
        )
        session.add(user)
        await session.flush()
        session.add(Profile(user_id=user.id, resume={}, preferences=Preferences().model_dump()))
        await grant(session, user.id, "core", method="google_signup")
        created = True
    await session.commit()
    await session.refresh(user)
    dest = _safe_next(data.get("next"), "/onboarding" if created else "/dashboard")
    r = RedirectResponse(f"{settings.app_url.rstrip('/')}{dest}", status_code=303)
    _issue(r, user)
    r.delete_cookie(STATE_COOKIE, path="/")
    log.info("google_signin.ok", created=created)
    return r

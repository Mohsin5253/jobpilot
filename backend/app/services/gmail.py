"""Sending from the user's Gmail through Google OAuth, instead of storing a mail password.

Scopes: `gmail.send` (send only: no reading, no drafts, no labels) plus `openid email` to learn which address the
user connected. gmail.send is a *sensitive* scope, not a restricted one, so it needs Google's app verification but no
third-party security assessment. The refresh token is encrypted with ENCRYPTION_KEY (kept in the environment, never in
the database) and access tokens are fetched per send and never stored.
"""

import base64
import hashlib
import hmac
import secrets
import time
import uuid
from urllib.parse import urlencode

import httpx

from app.config import settings

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
SCOPES = "openid email https://www.googleapis.com/auth/gmail.send"
STATE_TTL_S = 600


class GmailError(RuntimeError):
    pass


class GmailRevoked(GmailError):
    """The user revoked access in their Google account (or the token expired): they have to reconnect."""


def redirect_uri() -> str:
    return f"{settings.app_url.rstrip('/')}/api/mail/google/callback"


def _sign(payload: str) -> str:
    return hmac.new(settings.jwt_secret.encode(), payload.encode(), hashlib.sha256).hexdigest()[:32]


def make_state(user_id: uuid.UUID) -> str:
    """CSRF protection for the OAuth round trip: bound to the user, signed, valid for ten minutes."""
    payload = f"{user_id}.{int(time.time()) + STATE_TTL_S}.{secrets.token_hex(8)}"
    return f"{payload}.{_sign(payload)}"


def check_state(state: str, user_id: uuid.UUID) -> bool:
    try:
        uid, exp, nonce, sig = state.split(".")
    except ValueError:
        return False
    payload = f"{uid}.{exp}.{nonce}"
    return hmac.compare_digest(sig, _sign(payload)) and uid == str(user_id) and int(exp) >= time.time()


def auth_url(state: str, login_hint: str = "") -> str:
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": redirect_uri(),
        "response_type": "code",
        "scope": SCOPES,
        "access_type": "offline",  # a refresh token, so approved sends work later
        "prompt": "consent",
        "include_granted_scopes": "false",
        "state": state,
    }
    if login_hint:
        params["login_hint"] = login_hint
    return f"{AUTH_URL}?{urlencode(params)}"


async def exchange_code(code: str) -> tuple[str, str]:
    """Returns (refresh_token, email)."""
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post(
            TOKEN_URL,
            data={"code": code, "client_id": settings.google_client_id, "client_secret": settings.google_client_secret, "redirect_uri": redirect_uri(), "grant_type": "authorization_code"},
        )
        if r.status_code != 200:
            raise GmailError(f"Google didn't accept the sign-in ({r.status_code})")
        tok = r.json()
        if "gmail.send" not in tok.get("scope", ""):
            raise GmailError("Sending permission wasn't granted. Tick the Gmail box on Google's screen and try again.")
        refresh = tok.get("refresh_token")
        if not refresh:
            raise GmailError("Google didn't return a long-lived token. Remove JobPilot at myaccount.google.com/permissions and connect again.")
        info = await c.get(USERINFO_URL, headers={"authorization": f"Bearer {tok['access_token']}"})
        email = info.json().get("email") if info.status_code == 200 else None
        if not email:
            raise GmailError("Couldn't read which Google account you connected")
        return refresh, email.lower()


async def access_token(refresh_token: str) -> str:
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post(
            TOKEN_URL,
            data={"refresh_token": refresh_token, "client_id": settings.google_client_id, "client_secret": settings.google_client_secret, "grant_type": "refresh_token"},
        )
    if r.status_code == 400 and r.json().get("error") == "invalid_grant":
        raise GmailRevoked("Google access was revoked or expired. Reconnect Gmail in Settings.")
    if r.status_code != 200:
        raise GmailError(f"Couldn't get a Google access token ({r.status_code})")
    return r.json()["access_token"]


async def send_raw(refresh_token: str, message: bytes) -> str:
    """Sends an RFC 822 message as the connected user; returns Gmail's message id."""
    token = await access_token(refresh_token)
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(SEND_URL, headers={"authorization": f"Bearer {token}"}, json={"raw": base64.urlsafe_b64encode(message).decode()})
    if r.status_code in (401, 403):
        raise GmailRevoked("Gmail refused the send. Reconnect Gmail in Settings.")
    if r.status_code == 429:
        raise GmailError("Gmail's sending limit for your account was reached. Try again later.")
    if r.status_code >= 300:
        raise GmailError(f"Gmail couldn't send the email ({r.status_code})")
    return r.json().get("id", "")


async def revoke(refresh_token: str) -> None:
    """Best effort: tells Google to drop the grant when the user disconnects."""
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            await c.post(REVOKE_URL, data={"token": refresh_token})
    except httpx.HTTPError:
        pass

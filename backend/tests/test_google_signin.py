"""Sign in / sign up with Google: state bound to the browser, consent + 18+ for new accounts, linking by verified email."""

from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import respx
from sqlalchemy import select

from app.config import settings
from app.db import session_scope
from app.models import Consent, User
from app.services import gmail


@pytest.fixture
def google(monkeypatch):
    monkeypatch.setattr(settings, "google_client_id", "cid")
    monkeypatch.setattr(settings, "google_client_secret", "sec")


def _mock(sub="g-1", email="neha@gmail.com", verified=True, name="Neha"):
    respx.post(gmail.TOKEN_URL).mock(return_value=httpx.Response(200, json={"access_token": "at"}))
    respx.get(gmail.USERINFO_URL).mock(return_value=httpx.Response(200, json={"sub": sub, "email": email, "email_verified": verified, "name": name}))


async def _round_trip(client, **params):
    r = await client.get("/api/auth/google/start", params=params)
    assert r.status_code == 303
    loc = r.headers["location"]
    if "accounts.google.com" not in loc:
        return loc
    q = parse_qs(urlparse(loc).query)
    assert q["scope"] == ["openid email profile"]  # sign-in only: no Gmail scope
    cb = await client.get("/api/auth/google/callback", params={"code": "c", "state": q["state"][0]})
    return cb


async def test_providers_flag(client, google):
    assert (await client.get("/api/auth/providers")).json() == {"google": True}


@respx.mock
async def test_sign_up_needs_both_confirmations_then_creates_the_account(client, google):
    loc = await _round_trip(client, mode="register", adult=1, consent=0)
    assert loc.endswith("/register?google=confirm")
    _mock()
    cb = await _round_trip(client, mode="register", adult=1, consent=1)
    assert cb.status_code == 303 and cb.headers["location"].endswith("/onboarding") and "jp_session=" in cb.headers.get("set-cookie", "")
    async with session_scope() as s:
        u = (await s.execute(select(User).where(User.email == "neha@gmail.com"))).scalar_one()
        assert u.google_sub == "g-1" and u.adult_confirmed_at and u.name == "Neha"
        c = (await s.execute(select(Consent).where(Consent.user_id == u.id))).scalar_one()
        assert c.purpose == "core" and c.method == "google_signup"
    me = await client.get("/api/auth/me")  # the session cookie works
    assert me.json()["email"] == "neha@gmail.com"


@respx.mock
async def test_login_without_an_account_goes_to_register(client, google):
    _mock(sub="g-2", email="new@gmail.com")
    cb = await _round_trip(client, mode="login")
    assert cb.headers["location"].endswith("/register?google=no_account")
    async with session_scope() as s:
        assert (await s.execute(select(User).where(User.email == "new@gmail.com"))).scalar_one_or_none() is None


@respx.mock
async def test_existing_password_account_is_linked_by_verified_email(authed, client, google):
    client.headers.pop("authorization", None)
    _mock(sub="g-3", email="aarav@example.com")
    cb = await _round_trip(client, mode="login", next="/approvals")
    assert cb.headers["location"].endswith("/approvals")
    async with session_scope() as s:
        assert (await s.execute(select(User.google_sub).where(User.email == "aarav@example.com"))).scalar_one() == "g-3"


@respx.mock
async def test_unverified_email_forged_state_and_other_browser_are_refused(client, google):
    _mock(email="x@gmail.com", verified=False)
    assert (await _round_trip(client, mode="register", adult=1, consent=1)).headers["location"].endswith("google=unverified")
    r = await client.get("/api/auth/google/callback", params={"code": "c", "state": "abc.def"})
    assert r.headers["location"].endswith("google=expired")
    start = await client.get("/api/auth/google/start", params={"mode": "login"})
    state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
    client.cookies.clear()  # the callback arrives in a browser that didn't start the flow
    r = await client.get("/api/auth/google/callback", params={"code": "c", "state": state})
    assert r.headers["location"].endswith("google=expired")
    assert "?next=//evil.example" not in (await client.get("/api/auth/google/start", params={"mode": "login", "next": "//evil.example"})).headers["location"]

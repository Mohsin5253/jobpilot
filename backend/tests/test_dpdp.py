"""Step 2: age gate, itemized consent records, Gmail OAuth sending (gmail.send only), send spacing, rights
requests and the 12-month inactivity retention."""

from datetime import UTC, datetime, timedelta
from email import message_from_bytes
from pathlib import Path
import base64
import json

import httpx
import pytest
import respx
from sqlalchemy import select, update

from app.config import settings
from app.db import session_scope
from app.models import Consent, MailAccount, RightsRequest, User
from app.security import decrypt_secret
from app.services import gmail
from app.services.mailer import MailNotConnected, SendTooSoon, send_as_user
from app.services.retention import inactive_accounts_sweep

SAMPLE = Path(__file__).resolve().parents[1] / "evals" / "data" / "sample_resume.md"


async def _me(c) -> User:
    async with session_scope() as s:
        return (await s.execute(select(User).where(User.email == "aarav@example.com"))).scalar_one()


async def test_registration_needs_age_confirmation(client):
    r = await client.post("/api/auth/register", json={"consent": True, "email": "kid@example.com", "password": "password123"})
    assert r.status_code == 403 and "18" in r.json()["detail"]
    async with session_scope() as s:
        assert (await s.execute(select(User).where(User.email == "kid@example.com"))).scalar_one_or_none() is None  # nothing stored
    r = await client.post("/api/auth/register", json={"consent": True, "adult": True, "email": "adult@example.com", "password": "password123"})
    assert r.status_code == 201 and r.json()["user"]["adult_confirmed_at"]


async def test_unconfirmed_age_blocks_processing_until_confirmed(authed):
    assert (await authed.post("/api/profile/resume", files={"file": ("resume.md", SAMPLE.read_bytes(), "text/markdown")})).status_code == 200
    async with session_scope() as s:
        await s.execute(update(User).values(adult_confirmed_at=None))  # an account from before the age gate
    r = await authed.post("/api/runs")
    assert r.status_code == 403 and r.json()["code"] == "age_not_confirmed"
    assert (await authed.post("/api/account/age", json={"adult": False})).status_code == 403
    assert (await authed.post("/api/runs")).status_code == 403
    assert (await authed.post("/api/account/age", json={"adult": True})).status_code == 200
    assert (await authed.post("/api/runs")).status_code == 202


async def test_itemized_notice_and_consent_records(client, authed):
    notice = (await client.get("/api/consents/notice")).json()
    purposes = {p["purpose"]: p for p in notice["purposes"]}
    assert {"core", "sending", "public_proof", "whatsapp", "college_share", "ledger"} <= purposes.keys()
    assert all(p["data"] and p["why"] and p["retention"] and p["withdraw"] for p in purposes.values())

    assert (await authed.put("/api/consents/whatsapp", json={"granted": True})).status_code == 200
    assert (await authed.put("/api/consents/whatsapp", json={"granted": False})).status_code == 200  # as easy as giving
    history = (await authed.get("/api/consents/history")).json()
    wa = [h for h in history if h["purpose"] == "whatsapp"]
    assert wa[0]["withdrawn_at"] and wa[0]["notice_version"] == settings.consent_version and wa[0]["method"] == "checkbox"
    core = next(h for h in history if h["purpose"] == "core")
    assert core["withdrawn_at"] is None
    export = (await authed.get("/api/account/export")).json()
    assert {c["purpose"] for c in export["consents"]} >= {"core", "whatsapp"} and export["age_confirmed_at"]


async def test_app_password_connection_records_sending_consent_and_disconnect_withdraws_it(authed, monkeypatch):
    async def ok(_):
        return None

    monkeypatch.setattr("app.api.routes.account.verify_login", ok)
    assert (await authed.put("/api/mail-account", json={"username": "aarav@gmail.com", "password": "abcd efgh ijkl mnop"})).status_code == 200
    me = await _me(authed)
    async with session_scope() as s:
        c = (await s.execute(select(Consent).where(Consent.user_id == me.id, Consent.purpose == "sending"))).scalar_one()
        assert c.method == "app_password" and c.withdrawn_at is None
    # Withdrawing the purpose stops sending at once, even with the mailbox still connected.
    assert (await authed.put("/api/consents/sending", json={"granted": False})).status_code == 200
    with pytest.raises(MailNotConnected):
        await send_as_user(me.id, "hr@acme.example", "Hi", "Body")
    assert (await authed.delete("/api/mail-account")).status_code == 204


@respx.mock
async def test_gmail_oauth_connect_and_send(authed, monkeypatch):
    monkeypatch.setattr(settings, "google_client_id", "cid")
    monkeypatch.setattr(settings, "google_client_secret", "csecret")
    assert (await authed.get("/api/mail-account")).json()["google_available"] is True
    url = (await authed.get("/api/mail/google/start")).json()["url"]
    assert "gmail.send" in url and "gmail.readonly" not in url and "access_type=offline" in url
    me = await _me(authed)

    # A forged or someone else's state is refused before talking to Google.
    r = await authed.get("/api/mail/google/callback", params={"code": "c", "state": "x.y.z.w"})
    assert r.status_code == 303 and "mail=expired" in r.headers["location"]

    respx.post(gmail.TOKEN_URL).mock(
        side_effect=[
            httpx.Response(200, json={"access_token": "at1", "refresh_token": "rt-secret", "scope": "openid email https://www.googleapis.com/auth/gmail.send"}),
            httpx.Response(200, json={"access_token": "at2"}),
            httpx.Response(200, json={"access_token": "at3"}),
        ]
    )
    respx.get(gmail.USERINFO_URL).mock(return_value=httpx.Response(200, json={"email": "Aarav@Gmail.com"}))
    r = await authed.get("/api/mail/google/callback", params={"code": "c", "state": gmail.make_state(me.id)})
    assert r.status_code == 303 and "mail=connected" in r.headers["location"]
    async with session_scope() as s:
        acct = await s.get(MailAccount, me.id)
        assert acct.provider == "gmail_oauth" and acct.password_enc is None and acct.from_email == "aarav@gmail.com"
        assert "rt-secret" not in acct.refresh_token_enc and decrypt_secret(acct.refresh_token_enc) == "rt-secret"
        consent = (await s.execute(select(Consent).where(Consent.user_id == me.id, Consent.purpose == "sending"))).scalar_one()
        assert consent.method == "google_oauth"

    sent = respx.post(gmail.SEND_URL).mock(return_value=httpx.Response(200, json={"id": "m1"}))
    await send_as_user(me.id, "hr@acme.example", "ML Intern", "Hello")
    raw = base64.urlsafe_b64decode(json.loads(sent.calls.last.request.content)["raw"])
    msg = message_from_bytes(raw)
    assert msg["To"] == "hr@acme.example" and sent.calls.last.request.headers["authorization"] == "Bearer at2"

    # Sends from one mailbox are spaced at least 90 seconds apart.
    with pytest.raises(SendTooSoon):
        await send_as_user(me.id, "hr@acme.example", "Again", "Hello")
    async with session_scope() as s:
        await s.execute(update(MailAccount).values(last_sent_at=datetime.now(UTC) - timedelta(seconds=settings.send_spacing_s + 1)))
    await send_as_user(me.id, "hr@acme.example", "Again", "Hello")
    assert sent.call_count == 2


async def test_rights_requests_have_a_30_day_due_date(client, authed):
    r = await authed.post("/api/rights", json={"kind": "nomination", "details": "My mother, if I can't act"})
    assert r.status_code == 201
    due = datetime.fromisoformat(r.json()["due_at"])
    assert timedelta(days=29) < due - datetime.now(UTC) <= timedelta(days=30)
    assert (await client.post("/api/public/grievance", json={"email": "someone@example.com", "details": "Please tell me what data you hold"})).status_code == 201
    assert (await authed.get("/api/admin/rights")).status_code == 403
    me = await _me(authed)
    async with session_scope() as s:
        await s.execute(update(User).where(User.id == me.id).values(is_admin=True))
    rows = (await authed.get("/api/admin/rights")).json()
    assert len(rows) == 2
    res = await authed.post(f"/api/admin/rights/{rows[0]['id']}/resolve", json={"response": "Done"})
    assert res.json()["status"] == "resolved"
    async with session_scope() as s:
        assert (await s.execute(select(RightsRequest).where(RightsRequest.status == "open"))).scalars().all().__len__() == 1


async def test_inactive_accounts_are_warned_then_deleted(authed):
    now = datetime.now(UTC)
    me = await _me(authed)
    async with session_scope() as s:
        await s.execute(update(User).where(User.id == me.id).values(last_seen_at=now - timedelta(days=340)))
    out = await inactive_accounts_sweep(now)
    assert out["inactive_warned"] == 1 and out["inactive_deleted"] == 0
    assert (await inactive_accounts_sweep(now))["inactive_warned"] == 0  # warned once
    # 31 days later, still unused: deleted.
    out = await inactive_accounts_sweep(now + timedelta(days=31))
    assert out["inactive_deleted"] == 1


async def test_returning_user_clears_the_inactivity_notice(authed):
    now = datetime.now(UTC)
    me = await _me(authed)
    async with session_scope() as s:
        await s.execute(update(User).where(User.id == me.id).values(last_seen_at=now - timedelta(days=340)))
    await inactive_accounts_sweep(now)
    async with session_scope() as s:
        await s.execute(update(User).where(User.id == me.id).values(last_seen_at=now + timedelta(days=1)))
    out = await inactive_accounts_sweep(now + timedelta(days=40))
    assert out["inactive_deleted"] == 0

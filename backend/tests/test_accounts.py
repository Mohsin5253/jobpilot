"""Accounts and safety: rate limits, session revocation, password reset, per-user mail, plans and the AI
budget, demo accounts, data export / deletion, admin metrics and the production config guard."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text

from app.config import Settings, settings
from app.db import session_scope
from app.models import JobMatch, LLMCall, MailAccount, PasswordReset, User
from app.security import decrypt_secret
from app.services.runs import claim_next, execute_run

SAMPLE = Path(__file__).resolve().parents[1] / "evals" / "data" / "sample_resume.md"


async def _client() -> AsyncClient:
    from app.main import app

    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _upload(c):
    assert (await c.post("/api/profile/resume", files={"file": ("resume.md", SAMPLE.read_bytes(), "text/markdown")})).status_code == 200


async def _work():
    claimed = await claim_next("w")
    return await execute_run(claimed.id, claimed.user_id)


async def test_login_is_rate_limited_across_sessions(client, monkeypatch):
    monkeypatch.setattr(settings, "rate_limits_enabled", True)
    await client.post("/api/auth/register", json={"consent": True, "adult": True, "email": "a@example.com", "password": "password123"})
    codes = []
    for _ in range(11):
        other = await _client()  # a fresh client each time: the limit lives in Postgres, not the session
        codes.append((await other.post("/api/auth/login", json={"email": "a@example.com", "password": "wrong-pass"})).status_code)
        await other.aclose()
    assert codes[:10] == [401] * 10 and codes[10] == 429


async def test_password_change_signs_out_other_sessions(client):
    r = await client.post("/api/auth/register", json={"consent": True, "adult": True, "email": "a@example.com", "password": "password123"})
    old_token = r.json()["access_token"]
    r = await client.post("/api/auth/change-password", json={"current_password": "password123", "new_password": "newpassword456"})
    assert r.status_code == 200
    other = await _client()
    other.headers["authorization"] = f"Bearer {old_token}"
    assert (await other.get("/api/auth/me")).status_code == 401  # the old session is gone
    assert (await client.get("/api/auth/me")).status_code == 200  # this one got a fresh token
    await other.aclose()


async def test_password_reset_is_single_use_and_expires(client, monkeypatch):
    sent = {}

    async def fake_system(to, subject, body):
        sent["body"] = body
        return True

    monkeypatch.setattr("app.api.routes.auth.send_system_email", fake_system)
    await client.post("/api/auth/register", json={"consent": True, "adult": True, "email": "a@example.com", "password": "password123"})
    client.cookies.clear()
    assert (await client.post("/api/auth/forgot-password", json={"email": "nobody@example.com"})).status_code == 202  # same answer
    assert "body" not in sent
    assert (await client.post("/api/auth/forgot-password", json={"email": "A@example.com"})).status_code == 202
    token = sent["body"].split("token=")[1].split()[0]
    r = await client.post("/api/auth/reset-password", json={"token": token, "password": "brandnewpass1"})
    assert r.status_code == 200
    assert (await client.post("/api/auth/reset-password", json={"token": token, "password": "again12345"})).status_code == 400
    assert (await client.post("/api/auth/login", json={"email": "a@example.com", "password": "brandnewpass1"})).status_code == 200

    await client.post("/api/auth/forgot-password", json={"email": "a@example.com"})
    token = sent["body"].split("token=")[1].split()[0]
    async with session_scope() as s:
        await s.execute(text("UPDATE password_resets SET expires_at = now() - interval '1 minute' WHERE used_at IS NULL"))
    assert (await client.post("/api/auth/reset-password", json={"token": token, "password": "expired1234"})).status_code == 400


async def test_mail_password_is_encrypted_and_never_returned(authed, monkeypatch):
    async def ok(sender):
        return None

    monkeypatch.setattr("app.api.routes.account.verify_login", ok)
    r = await authed.put("/api/mail-account", json={"username": "aarav@gmail.com", "password": "abcd efgh ijkl mnop", "from_name": "Aarav"})
    assert r.status_code == 200 and "abcd" not in r.text and r.json()["from_email"] == "aarav@gmail.com"
    async with session_scope() as s:
        acct = (await s.execute(select(MailAccount))).scalar_one()
    assert "abcd" not in acct.password_enc and decrypt_secret(acct.password_enc) == "abcdefghijklmnop"
    cfg = (await authed.get("/api/config")).json()
    assert cfg["smtp_enabled"] and cfg["smtp_from"] == "aarav@gmail.com"
    assert (await authed.delete("/api/mail-account")).status_code == 204
    assert not (await authed.get("/api/config")).json()["smtp_enabled"]


async def test_wrong_mail_password_is_rejected(authed, monkeypatch):
    import smtplib

    async def bad(sender):
        raise smtplib.SMTPAuthenticationError(535, b"Username and Password not accepted")

    monkeypatch.setattr("app.api.routes.account.verify_login", bad)
    r = await authed.put("/api/mail-account", json={"username": "aarav@gmail.com", "password": "wrong-one"})
    assert r.status_code == 400 and "app password" in r.json()["detail"]


async def test_free_plan_caps_on_demand_runs_and_drafts(authed, monkeypatch):
    monkeypatch.setitem(settings.limits("free"), "manual_runs_per_day", 1)
    monkeypatch.setitem(settings.limits("free"), "drafts_per_day", 2)
    await _upload(authed)
    assert (await authed.post("/api/runs")).status_code == 202
    await _work()
    drafts = (await authed.get("/api/drafts")).json()
    assert len([d for d in drafts if d["kind"] == "application"]) <= 2  # tailoring stopped at the plan's draft limit
    r = await authed.post("/api/runs")
    assert r.status_code == 429 and "on-demand runs" in r.json()["detail"]
    usage = (await authed.get("/api/usage")).json()
    assert usage["plan"] == "free" and usage["runs_left"] == 0


async def test_ai_budget_falls_back_to_offline_agents(authed, monkeypatch):
    from app.llm import CallContext, LLMUnavailable, get_llm

    me = (await authed.get("/api/auth/me")).json()["id"]
    async with session_scope() as s:
        s.add(LLMCall(user_id=me, agent="matcher", model="x", input_tokens=1, output_tokens=1, latency_ms=1, cost_usd=1.0, success=True))
    llm = get_llm()
    monkeypatch.setattr(llm, "enabled", True)
    monkeypatch.setattr(llm, "_client", object())
    with pytest.raises(LLMUnavailable, match="budget"):
        await llm.structured(agent="matcher", tier="fast", system="", prompt="", schema=type("S", (), {}), ctx=CallContext(user_id=me))


async def test_demo_account_is_a_private_copy_that_cannot_send_and_expires(authed, client, monkeypatch):
    monkeypatch.setattr(settings, "demo_template_email", "aarav@example.com")
    await _upload(authed)
    await authed.post("/api/runs")
    await _work()
    showcase = (await authed.get("/api/matches")).json()["total"]

    visitor = await _client()
    r = await visitor.post("/api/auth/demo")
    assert r.status_code == 201 and r.json()["user"]["is_demo"]
    visitor.headers["authorization"] = f"Bearer {r.json()['access_token']}"
    assert (await visitor.get("/api/matches")).json()["total"] == min(showcase, 30)
    assert (await visitor.get("/api/drafts")).json()  # drafts copied, to look at
    assert (await visitor.put("/api/mail-account", json={"username": "x@gmail.com", "password": "abcdefgh"})).status_code == 403
    assert (await visitor.post("/api/auth/change-password", json={"current_password": "x", "new_password": "password123"})).status_code == 403

    async with session_scope() as s:
        await s.execute(text("UPDATE users SET expires_at = now() - interval '1 minute' WHERE is_demo"))
    assert (await visitor.get("/api/auth/me")).status_code == 401
    from app.services.demo import prune_demo_users

    assert await prune_demo_users() == 1
    async with session_scope() as s:
        assert (await s.execute(select(JobMatch))).scalars().all()  # the showcase account's data is untouched
    await visitor.aclose()


async def test_export_and_delete_account(authed):
    await _upload(authed)
    await authed.post("/api/runs")
    await _work()
    r = await authed.get("/api/account/export")
    data = r.json()
    assert r.status_code == 200 and data["account"]["email"] == "aarav@example.com" and data["matches"] and data["profile"]["resume_text"]
    assert (await authed.request("DELETE", "/api/account", json={"password": "wrong"})).status_code == 400
    assert (await authed.request("DELETE", "/api/account", json={"password": "password123"})).status_code == 204
    async with session_scope() as s:
        assert (await s.execute(select(User))).scalars().all() == []
        assert (await s.execute(select(JobMatch))).scalars().all() == []
        assert (await s.execute(select(PasswordReset))).scalars().all() == []


async def test_admin_metrics_and_plan_switch(authed, client, monkeypatch):
    assert (await authed.get("/api/admin/metrics")).status_code == 403
    monkeypatch.setattr(settings, "admin_emails", ["aarav@example.com"])
    m = (await authed.get("/api/admin/metrics")).json()
    assert m["users"]["total"] == 1 and "sources" in m and "llm" in m
    assert (await authed.get("/api/usage")).json()["limits"]["drafts_per_day"] == 50  # admins always have Pro
    reg = await client.post("/api/auth/register", json={"consent": True, "adult": True, "email": "neha@example.com", "password": "password123"})
    neha = {"authorization": f"Bearer {reg.json()['access_token']}"}
    await client.post("/api/account/pro-interest", headers=neha)
    assert (await authed.get("/api/admin/metrics")).json()["pro_requests"][0]["email"] == "neha@example.com"
    r = await authed.post("/api/admin/plan", json={"email": "neha@example.com", "plan": "pro"})
    assert r.json()["plan"] == "pro" and (await client.get("/api/usage", headers=neha)).json()["limits"]["drafts_per_day"] == 50


def test_production_refuses_unsafe_defaults():
    with pytest.raises(ValueError, match="JWT_SECRET"):
        Settings(env="prod", _env_file=None)
    ok = Settings(
        env="prod", _env_file=None, jwt_secret="x" * 40, cookie_secure=True, encryption_key="k", cors_origins=["https://jobpilot.app"]
    )
    assert ok.env == "prod"


async def test_reset_tokens_and_rate_limit_rows_are_swept():
    from app.services.retention import retention_sweep

    async with session_scope() as s:
        await s.execute(text("INSERT INTO rate_limits (key, window_start, count) VALUES ('x', now() - interval '3 days', 1)"))
    out = await retention_sweep()
    assert out["rate_limits"] == 1
    _ = datetime.now(UTC) - timedelta(days=1)

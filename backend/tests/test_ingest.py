"""Shared ingestion: one fetch per board for everyone, one quota budget for the service, and only the users a
new job could fit are woken up."""

from pathlib import Path

import httpx
import respx
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.config import settings
from app.db import session_scope
from app.models import AgentRun, SourceTarget
from app.services.ingest import ingest_tick, sync_targets
from app.services.runs import claim_next, execute_run

SAMPLE = Path(__file__).resolve().parents[1] / "evals" / "data" / "sample_resume.md"
LONG = "We are hiring a machine learning intern to build Python models with scikit-learn and SQL. " * 5


async def _user(email: str, **prefs_update) -> AsyncClient:
    from app.main import app

    c = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    r = await c.post("/api/auth/register", json={"consent": True, "email": email, "password": "password123"})
    c.headers["authorization"] = f"Bearer {r.json()['access_token']}"
    assert (await c.post("/api/profile/resume", files={"file": ("resume.md", SAMPLE.read_bytes(), "text/markdown")})).status_code == 200
    if prefs_update:
        prefs = (await c.get("/api/profile")).json()["preferences"]
        await c.put("/api/profile", json={"preferences": {**prefs, **prefs_update}})
    return c


def _greenhouse(board: str, title: str = "Machine Learning Intern"):
    listing = respx.get(f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs").mock(return_value=httpx.Response(200, json={"jobs": [
        {"id": 1, "title": title, "absolute_url": f"https://{board}.example/1", "location": {"name": "Bengaluru, India"}},
    ]}))
    respx.get(f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs/1").mock(return_value=httpx.Response(200, json={"content": LONG}))
    return listing


async def _queued_users() -> set:
    async with session_scope() as s:
        return set((await s.execute(select(AgentRun.user_id).where(AgentRun.status == "queued"))).scalars())


@respx.mock
async def test_two_users_on_the_same_board_cost_one_fetch_and_both_wake(monkeypatch):
    monkeypatch.setattr(settings, "demo_source", False)
    listing = _greenhouse("acme")
    a = await _user("a@example.com", greenhouse_boards=["acme"])
    b = await _user("b@example.com", greenhouse_boards=["Acme"])  # same board, different spelling
    out = await ingest_tick()
    assert listing.call_count == 1  # fetched once for both
    assert out["new"] == 1 and out["runs"] == 2
    async with session_scope() as s:
        target = (await s.execute(select(SourceTarget).where(SourceTarget.source == "greenhouse"))).scalar_one()
    assert target.target == "acme" and target.demand == 2 and target.last_status == "ok"

    await ingest_tick()  # inside the board's polite gap: not fetched again
    assert listing.call_count == 1
    await a.aclose()
    await b.aclose()


@respx.mock
async def test_quota_api_has_one_budget_for_the_whole_service(monkeypatch):
    monkeypatch.setattr(settings, "demo_source", False)
    monkeypatch.setattr(settings, "jsearch_api_key", "k")
    route = respx.get("https://jsearch.p.rapidapi.com/search").mock(return_value=httpx.Response(200, json={"data": {"jobs": []}}))
    a = await _user("a@example.com")
    b = await _user("b@example.com", tracks=["non_technical"])  # wants different searches
    await sync_targets()
    async with session_scope() as s:
        queries = (await s.execute(select(SourceTarget).where(SourceTarget.source == "jsearch", SourceTarget.target != "*"))).scalars().all()
    assert len(queries) >= 3  # the union of both users' searches
    for _ in range(3):
        await ingest_tick()
    assert route.call_count == 1  # one request per budget gap, however many users or searches
    await a.aclose()
    await b.aclose()


@respx.mock
async def test_new_job_wakes_only_users_it_could_fit(monkeypatch):
    monkeypatch.setattr(settings, "demo_source", False)
    _greenhouse("acme")
    tech = await _user("tech@example.com", greenhouse_boards=["acme"])
    other = await _user("biz@example.com", greenhouse_boards=["acme"], tracks=["non_technical"])
    await ingest_tick()
    me = (await tech.get("/api/auth/me")).json()["id"]
    assert {str(u) for u in await _queued_users()} == {me}  # the technical role doesn't fit the business-only user
    await tech.aclose()
    await other.aclose()


@respx.mock
async def test_far_jobs_wake_nobody(monkeypatch):
    monkeypatch.setattr(settings, "demo_source", False)
    monkeypatch.setattr(settings, "fanout_min_semantic", 100.0)
    _greenhouse("acme")
    c = await _user("a@example.com", greenhouse_boards=["acme"])
    out = await ingest_tick()
    assert out["new"] == 1 and out["runs"] == 0
    await c.aclose()


@respx.mock
async def test_refresh_run_reads_the_index_without_any_http(monkeypatch):
    monkeypatch.setattr(settings, "demo_source", False)
    _greenhouse("acme")
    c = await _user("a@example.com", greenhouse_boards=["acme"])
    await ingest_tick()
    calls_before = len(respx.calls)
    claimed = await claim_next("w")
    assert await execute_run(claimed.id, claimed.user_id) == "awaiting_approval"
    assert len(respx.calls) == calls_before  # the Scout fetched nothing itself
    matches = (await c.get("/api/matches")).json()
    assert matches["total"] == 1 and matches["items"][0]["job"]["company"] == "Acme"
    await c.aclose()


@respx.mock
async def test_broken_board_backs_off_and_reports(monkeypatch):
    monkeypatch.setattr(settings, "demo_source", False)
    respx.get("https://boards-api.greenhouse.io/v1/boards/gone/jobs").mock(return_value=httpx.Response(404))
    c = await _user("a@example.com", greenhouse_boards=["gone"])
    out = await ingest_tick()
    assert out["report"]["greenhouse"].startswith("failed")
    async with session_scope() as s:
        t = (await s.execute(select(SourceTarget).where(SourceTarget.target == "gone"))).scalar_one()
    assert t.failures == 1 and t.last_status.startswith("failed")
    await c.aclose()

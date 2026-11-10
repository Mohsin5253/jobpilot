"""Landing-page counters: real aggregates, demo accounts excluded, cached for five minutes, no sign-in."""

from datetime import UTC, datetime

from app.api.routes import public
from app.config import settings
from app.db import session_scope
from app.models import AgentRun, Job, JobMatch, OutreachDraft, User


async def _seed():
    now = datetime.now(UTC)
    async with session_scope() as s:
        real = User(email="real@example.com", password_hash="x")
        demo = User(email="d@demo.example", password_hash="x", is_demo=True)
        jobs = [
            Job(source="t", external_id="1", company="Acme", title="Intern", legit_status="verified", legit_checked_at=now),
            Job(source="t", external_id="2", company="Acme", title="Intern 2", legit_status="caution", legit_checked_at=now),
            Job(source="t", external_id="3", company="Scam", title="Intern 3", legit_status="suspicious", legit_checked_at=now),
            Job(source="t", external_id="4", company="New", title="Unchecked"),
        ]
        s.add_all([real, demo, *jobs])
        await s.flush()
        for user, statuses in ((real, ["approved", "sent", "pending", "rejected"]), (demo, ["sent"])):
            for i, st in enumerate(statuses):
                m = JobMatch(user_id=user.id, job_id=jobs[i].id)
                s.add(m)
                await s.flush()
                s.add(OutreachDraft(user_id=user.id, match_id=m.id, status=st))
        s.add_all(
            [
                AgentRun(user_id=real.id, status="completed", cost_usd=0.002),
                AgentRun(user_id=real.id, status="awaiting_approval", cost_usd=0.004),
                AgentRun(user_id=real.id, status="failed", cost_usd=1.0),  # failed runs don't count
                AgentRun(user_id=demo.id, status="completed", cost_usd=1.0),  # nor do demo accounts
            ]
        )


async def test_public_stats_are_real_aggregates(client):
    public.reset_cache()
    r = await client.get("/api/public/stats")
    assert r.status_code == 200
    empty = r.json()
    assert empty["postings_verified"] == 0 and empty["avg_cost_inr_per_run"] is None and empty["beta"] is True

    await _seed()
    public.reset_cache()
    r = await client.get("/api/public/stats")
    body = r.json()
    assert body["postings_verified"] == 3
    assert body["scams_flagged"] == 1
    assert body["applications_approved"] == 2  # approved + sent, demo excluded
    assert body["runs_counted"] == 2
    assert body["avg_cost_inr_per_run"] == round(0.003 * settings.usd_inr_rate, 2)
    assert r.headers["cache-control"] == "public, max-age=300, s-maxage=300"


async def test_public_stats_are_cached(client):
    public.reset_cache()
    first = (await client.get("/api/public/stats")).json()
    await _seed()
    assert (await client.get("/api/public/stats")).json() == first  # within five minutes: the cached answer
    public.reset_cache()

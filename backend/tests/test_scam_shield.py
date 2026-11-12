"""Step 3: Scam Shield (public) and Verifier v2 (pipeline)."""

import json
import statistics
import time
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func, select, text

from app.agents.verifier import apply_verdict, ghost_score
from app.db import session_scope
from app.models import DraftStatus, Job, JobMatch, OutreachDraft, ScamReport, User, Verification
from app.services import scam_shield as shield

DATA = Path(__file__).resolve().parents[1] / "evals" / "data"
EXPECT = {"scam": "Likely scam", "suspicious": "Suspicious", "safe": "Likely safe"}


def _samples(name: str) -> list[dict]:
    return [json.loads(line) for line in (DATA / name).read_text().splitlines() if line.strip()]


def test_labelled_set_accuracy_and_speed():
    samples = _samples("scam_samples.jsonl") + _samples("scam_holdout.jsonl")
    assert len(samples) >= 40
    kinds = {s["kind"] for s in samples}
    assert {"fee", "task", "gov", "legit"} <= kinds and any(k.endswith(("_hi", "_mr", "_hinglish")) for k in kinds)
    times, correct = [], 0
    for s in samples:
        t = time.perf_counter()
        r = shield.analyze(s["text"], s["url"])
        times.append(time.perf_counter() - t)
        correct += r.verdict == EXPECT[s["label"]]
    assert correct / len(samples) >= 0.9, f"{correct}/{len(samples)}"
    # Held-out samples were written after the rules were tuned on the main set.
    holdout = _samples("scam_holdout.jsonl")
    assert sum(shield.analyze(s["text"], s["url"]).verdict == EXPECT[s["label"]] for s in holdout) / len(holdout) >= 0.9
    assert statistics.quantiles(times, n=20)[-1] < 0.05  # p95 of the rules, far under the 4 s budget


def test_each_check_has_status_and_evidence():
    r = shield.analyze("Pay refundable registration fee Rs 999 to hr.team@ybl. Share the OTP to confirm. Limited seats!")
    by = {c.id: c for c in r.checks}
    assert by["fee"].status == "fail" and by["fee"].evidence
    assert by["upi"].status == "fail" and any("@ybl" in e for e in by["upi"].evidence)
    assert by["ids"].status == "fail" and by["urgency"].status == "warn"
    assert r.verdict == "Likely scam" and 0 <= r.score <= 100
    assert shield.lookalike("amazon-careers-hiring.in") and shield.lookalike("lnfosys.com") and not shield.lookalike("amazon.jobs")
    assert not shield.lookalike("careers.google.com")


def test_ai_opinion_can_only_make_it_stricter():
    safe = shield.analyze("Your interview with Groww is on Monday at 11. Apply status on boards.greenhouse.io/groww")
    assert shield.stricter(safe, "legitimate").verdict == "Likely safe"
    scam = shield.analyze("Pay ₹999 training fee to join")
    assert shield.stricter(scam, "legitimate").verdict == "Likely scam"
    assert shield.stricter(shield.analyze("Hi, interested in an internship?"), "fee_scam").verdict == "Likely scam"


async def test_public_check_needs_no_login_and_stores_no_content(client):
    msg = "Congrats! Selected without interview. Pay ₹1,499 refundable registration fee to priya.hr@okaxis. Call 9876543210 today itself."
    r = await client.post("/api/scam-check", json={"text": msg})
    assert r.status_code == 200
    body = r.json()
    assert body["verdict"] == "Likely scam" and body["advice"] and any(c["evidence"] for c in body["checks"])
    assert any("1930" in a for a in body["advice"])
    async with session_scope() as s:
        v = await s.get(Verification, body["verification_id"])
        assert all(set(c) == {"id", "status"} for c in v.checks)  # no evidence stored
        dump = json.dumps((await s.execute(text("SELECT row_to_json(v) FROM verifications v"))).scalars().all())
        assert "9876543210" not in dump and "priya" not in dump and "1,499" not in dump
        assert (await s.execute(select(func.count()).select_from(ScamReport))).scalar_one() == 0
    assert (await client.post("/api/v1/scam-check", json={"text": msg})).json()["verdict"] == "Likely scam"
    r = await client.post("/api/scam-check", files={"file": ("offer.txt", "Pay the training fee of Rs 2000 via GPay".encode(), "text/plain")})
    assert r.json()["verdict"] == "Likely scam"
    assert (await client.post("/api/scam-check", json={"text": ""})).status_code == 422


async def test_report_stores_only_a_redacted_copy_with_consent(client):
    msg = "Pay Rs 999 fee to rahul.k@paytm or call +91 98765 43210. Email hr.desk@gmail.com, Aadhaar 1234 5678 9012"
    vid = (await client.post("/api/scam-check", json={"text": msg})).json()["verification_id"]
    assert (await client.post(f"/api/scam-check/{vid}/report", json={"text": msg, "consent": False})).status_code == 422
    assert (await client.post(f"/api/scam-check/{vid}/report", json={"text": "something else", "consent": True})).status_code == 404
    assert (await client.post(f"/api/scam-check/{vid}/report", json={"text": msg, "consent": True})).status_code == 201
    async with session_scope() as s:
        rep = (await s.execute(select(ScamReport))).scalar_one()
    for secret in ("rahul.k", "98765", "hr.desk", "1234 5678 9012"):
        assert secret not in rep.redacted_text
    assert "@paytm" in rep.redacted_text and "[phone]" in rep.redacted_text


async def _job(s, **kw) -> Job:
    j = Job(source="t", external_id=kw.pop("external_id", "1"), company=kw.pop("company", "Acme"), title=kw.pop("title", "Data Intern"),
            description=kw.pop("description", "Build dashboards with SQL and Python. " * 20), url=kw.pop("url", "https://boards.greenhouse.io/acme/1"),
            link_status="ok", **kw)
    s.add(j)
    await s.flush()
    return j


async def test_verifier_v2_records_a_verification_and_ghost_score_per_job():
    now = datetime.now(UTC)
    async with session_scope() as s:
        scam = await _job(s, external_id="2", description="Work from home. Pay a refundable security deposit of Rs 2,000 to hr@ybl before joining. " * 5)
        good = await _job(s)
        v1 = await apply_verdict(s, scam, now)
        v2 = await apply_verdict(s, good, now)
        assert v1.status == "suspicious" and v2.status == "verified"
        assert scam.verification_id and good.verification_id and scam.ghost_score is not None
        row = await s.get(Verification, scam.verification_id)
        assert row.verdict == "Likely scam" and row.opportunity_id == scam.id and any(c["status"] == "fail" and c["evidence"] for c in row.checks)
    stale = Job(source="t", external_id="9", company="X", title="Intern", description="short", url="https://x.example/1", link_status="unverified",
                posted_at=datetime(2026, 8, 1, tzinfo=UTC), last_seen_at=datetime(2026, 10, 1, tzinfo=UTC), repost_count=3)
    assert ghost_score(stale, now) >= 70 and ghost_score(good, now) <= 10


async def test_scam_flagged_postings_cannot_be_approved_or_sent(authed):
    import pytest
    from sqlalchemy.exc import IntegrityError

    async with session_scope() as s:
        me = (await s.execute(select(User))).scalar_one()
        job = await _job(s, description="Pay registration fee ₹999 to confirm your internship. " * 5)
        m = JobMatch(user_id=me.id, job_id=job.id, score=90)  # matched before the Verifier looked at it
        s.add(m)
        await s.flush()
        d = OutreachDraft(user_id=me.id, match_id=m.id, to_email="hr@acme.example", subject="Hi", email_body="Hello")
        s.add(d)
        await s.flush()
        draft_id, match_id, job_id = d.id, m.id, job.id
        await apply_verdict(s, job, datetime.now(UTC))  # blocked: its unsent draft is voided with the reason
    async with session_scope() as s:
        voided = await s.get(OutreachDraft, draft_id)
        assert voided.status == DraftStatus.voided and "scam" in voided.void_reason
    r = await authed.post(f"/api/drafts/{draft_id}/decision", json={"decision": "approve"})
    assert r.status_code == 409
    assert (await authed.post(f"/api/drafts/{draft_id}/send", json={})).status_code == 409
    # Enforced in the database too: no new match or draft for a blocked posting, whatever the code above it does.
    with pytest.raises(IntegrityError):
        async with session_scope() as s:
            s.add(JobMatch(user_id=me.id, job_id=job_id, score=95))
            await s.flush()
    with pytest.raises(IntegrityError):
        async with session_scope() as s:
            s.add(OutreachDraft(user_id=me.id, match_id=match_id, to_email="hr@acme.example", subject="Hi", email_body="Hello"))
            await s.flush()
    with pytest.raises(IntegrityError):
        async with session_scope() as s:
            row = await s.get(OutreachDraft, draft_id)
            row.status = DraftStatus.approved  # straight to the table, past every route
            await s.flush()


async def test_new_postings_get_a_verification_at_ingest():
    from app.services.job_store import store_postings
    from app.sources.base import Posting

    now = datetime.now(UTC)
    p = Posting(source="greenhouse", external_id="77", company="Acme", title="ML Intern", location="Bengaluru", url="https://boards.greenhouse.io/acme/77", description="Python, SQL. " * 60)
    res = await store_postings([p], now)
    async with session_scope() as s:
        j = await s.get(Job, res.inserted_ids[0])
        assert j.verification_id is not None and j.legit_status == "verified"

"""Production quality signals for /admin/quality, from metadata only (no prompt, reply or email text): verdict mix,
guard-fire rate, AI validation failures and fallbacks, approval outcomes, reply rate, cost per run, and alerts when a
signal shifts in a way that usually means something broke (a guard that never fires, a jump in VERIFIED)."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from app.config import settings


def _rate(n: float, d: float) -> float | None:
    return round(n / d, 4) if d else None


async def quality(s, days: int = 7) -> dict:
    now = datetime.now(UTC)
    since, before = now - timedelta(days=days), now - timedelta(days=2 * days)

    async def one(sql: str, **kw):
        return (await s.execute(text(sql), {"since": since, "before": before, **kw})).mappings().first() or {}

    async def rows(sql: str, **kw):
        return [dict(r) for r in (await s.execute(text(sql), {"since": since, "before": before, **kw})).mappings().all()]

    verdicts = await rows("SELECT coalesce(legit_status, 'unchecked') AS status, count(*) AS n FROM jobs WHERE fetched_at >= :since GROUP BY 1")
    prev = await rows("SELECT coalesce(legit_status, 'unchecked') AS status, count(*) AS n FROM jobs WHERE fetched_at >= :before AND fetched_at < :since GROUP BY 1")
    inj = await one("SELECT count(*) AS n FROM jobs WHERE fetched_at >= :since AND jsonb_array_length(injection_signals) > 0")
    guard = await one(
        "SELECT count(*) AS tailored, coalesce(sum((SELECT count(*) FROM jsonb_array_elements(t.bullets) b WHERE (b->>'reverted')::boolean)), 0) AS reverted, "
        "coalesce(sum(jsonb_array_length(t.bullets)), 0) AS bullets FROM tailored_resumes t WHERE t.created_at >= :since"
    )
    llm = await rows(
        "SELECT agent, count(*) AS calls, sum(CASE WHEN success THEN 0 ELSE 1 END) AS failed, sum(CASE WHEN attempts > 1 THEN 1 ELSE 0 END) AS repaired, "
        "percentile_disc(0.95) WITHIN GROUP (ORDER BY latency_ms) AS p95_ms FROM llm_calls WHERE created_at >= :since GROUP BY agent ORDER BY calls DESC"
    )
    approvals = await rows("SELECT action, count(*) AS n FROM approval_events WHERE created_at >= :since GROUP BY action")
    drafts = await rows("SELECT status, count(*) AS n FROM outreach_drafts WHERE created_at >= :since GROUP BY status")
    grants = await rows("SELECT coalesce(void_reason, CASE WHEN used_at IS NOT NULL THEN 'used' ELSE 'open' END) AS state, count(*) AS n FROM approval_grants WHERE created_at >= :since GROUP BY 1")
    rejects = await one("SELECT count(*) AS n, count(reject_reason) AS with_reason FROM outreach_drafts WHERE status = 'rejected' AND decided_at >= :since")
    outcomes = await one(
        "SELECT count(*) FILTER (WHERE stage IN ('applied','interview','offer','rejected')) AS applied, "
        "count(*) FILTER (WHERE outcome IN ('replied','interview','offer')) AS replied FROM job_matches WHERE applied_at >= :since"
    )
    cost = await one(
        "SELECT count(*) AS runs, avg(r.cost_usd) AS avg_usd FROM agent_runs r JOIN users u ON u.id = r.user_id "
        "WHERE r.created_at >= :since AND r.status = 'completed' AND NOT u.is_demo"
    )

    vmix = {r["status"]: r["n"] for r in verdicts}
    pmix = {r["status"]: r["n"] for r in prev}
    checked, pchecked = sum(v for k, v in vmix.items() if k != "unchecked"), sum(v for k, v in pmix.items() if k != "unchecked")
    verified_share, prev_verified_share = _rate(vmix.get("verified", 0), checked), _rate(pmix.get("verified", 0), pchecked)
    calls = sum(r["calls"] for r in llm)
    failed = sum(r["failed"] for r in llm)
    revert_rate = _rate(guard.get("reverted", 0), guard.get("bullets", 0))

    alerts = []
    if guard.get("tailored", 0) >= 20 and not guard.get("reverted"):
        alerts.append("Tailor's guard reverted nothing in 20+ tailored resumes: check that the guard still runs.")
    if verified_share is not None and prev_verified_share is not None and verified_share - prev_verified_share > 0.2 and checked >= 30:
        alerts.append(f"VERIFIED share jumped from {prev_verified_share:.0%} to {verified_share:.0%}: check the Verifier rules.")
    if calls >= 20 and failed / calls > 0.1:
        alerts.append(f"{failed / calls:.0%} of AI calls failed validation or the provider: check Groq limits and the schemas.")
    if inj.get("n", 0) >= 5:
        alerts.append(f"{inj['n']} postings carried text aimed at AI tools this period.")

    return {
        "window_days": days,
        "generated_at": now.isoformat(),
        "verifier": {"mix": vmix, "verified_share": verified_share, "previous_verified_share": prev_verified_share, "injection_flagged": inj.get("n", 0)},
        "tailor_guard": {"tailored": guard.get("tailored", 0), "bullets": guard.get("bullets", 0), "reverted": guard.get("reverted", 0), "revert_rate": revert_rate},
        "llm": {"calls": calls, "failure_rate": _rate(failed, calls), "repair_rate": _rate(sum(r["repaired"] for r in llm), calls), "by_agent": llm},
        "approvals": {"events": {r["action"]: r["n"] for r in approvals}, "drafts": {r["status"]: r["n"] for r in drafts}, "grants": {r["state"]: r["n"] for r in grants},
                      "rejected_with_reason": rejects.get("with_reason", 0), "rejected": rejects.get("n", 0)},
        "outcomes": {"applied": outcomes.get("applied", 0), "replied": outcomes.get("replied", 0), "reply_rate": _rate(outcomes.get("replied", 0), outcomes.get("applied", 0))},
        "cost": {"runs": cost.get("runs", 0), "avg_inr_per_run": round(float(cost["avg_usd"]) * settings.usd_inr_rate, 2) if cost.get("avg_usd") is not None else None},
        "alerts": alerts,
    }

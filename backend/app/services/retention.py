"""Daily housekeeping, so the database grows with active users rather than with time."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from app.config import settings
from app.db import session_scope
from app.logging import log
from app.services.demo import prune_demo_users


async def retention_sweep() -> dict[str, int]:
    now = datetime.now(UTC)
    out: dict[str, int] = {}
    async with session_scope() as s:
        if not (await s.execute(text("SELECT pg_try_advisory_xact_lock(724005)"))).scalar():
            return {}
        steps = {
            "llm_calls": ("DELETE FROM llm_calls WHERE created_at < :t", now - timedelta(days=settings.retain_llm_calls_days)),
            "ai_feature_cache": ("DELETE FROM ai_feature_cache WHERE created_at < :t", now - timedelta(days=30)),
            "notifications": ("DELETE FROM notifications WHERE created_at < :t", now - timedelta(days=settings.retain_notifications_days)),
            # Jobs nobody matched that no source has listed for a while (matched ones stay for the user's history).
            "jobs": (
                "DELETE FROM jobs j WHERE j.last_seen_at < :t AND NOT EXISTS (SELECT 1 FROM job_matches m WHERE m.job_id = j.id)",
                now - timedelta(days=settings.retain_unmatched_jobs_days),
            ),
            "rate_limits": ("DELETE FROM rate_limits WHERE window_start < :t", now - timedelta(days=1)),
            "password_resets": ("DELETE FROM password_resets WHERE expires_at < :t", now - timedelta(days=1)),
            "board_probes": ("DELETE FROM board_probes WHERE checked_at < :t", now - timedelta(days=30)),
            "source_targets": ("DELETE FROM source_targets WHERE demand = 0 AND target <> '*' AND COALESCE(last_fetched_at, next_due_at) < :t", now - timedelta(days=14)),
        }
        for name, (sql, cutoff) in steps.items():
            out[name] = (await s.execute(text(sql), {"t": cutoff})).rowcount or 0
        # LangGraph checkpoints of finished runs older than two weeks (the run rows and their traces stay).
        out["checkpoints"] = 0
        for table in ("checkpoint_writes", "checkpoint_blobs", "checkpoints"):
            exists = (await s.execute(text("SELECT to_regclass(:t) IS NOT NULL"), {"t": table})).scalar()
            if exists:
                res = await s.execute(
                    text(
                        f"DELETE FROM {table} WHERE thread_id IN (SELECT id::text FROM agent_runs "
                        "WHERE status IN ('completed', 'failed') AND COALESCE(finished_at, created_at) < :t)"
                    ),
                    {"t": now - timedelta(days=14)},
                )
                out["checkpoints"] += res.rowcount or 0
    out["demo_users"] = await prune_demo_users()
    out.update(await inactive_accounts_sweep(now))
    log.info("retention.sweep", **out)
    return out


async def inactive_accounts_sweep(now: datetime) -> dict[str, int]:
    """DPDP retention: an account nobody has used for a year is deleted, after an email notice a month earlier.
    Coming back (any signed-in request updates last_seen_at) cancels it."""
    from app.services.mailer import send_system_email

    delete_after = timedelta(days=settings.inactive_delete_days)
    notice_at = delete_after - timedelta(days=settings.inactive_notice_days)
    seen = "COALESCE(last_seen_at, created_at)"
    async with session_scope() as s:
        to_warn = (
            await s.execute(
                text(f"SELECT id, email FROM users WHERE NOT is_demo AND inactivity_notice_at IS NULL AND {seen} < :t"), {"t": now - notice_at}
            )
        ).all()
        if to_warn:
            await s.execute(text("UPDATE users SET inactivity_notice_at = :now WHERE id = ANY(:ids)"), {"now": now, "ids": [r.id for r in to_warn]})
        # Activity after the notice clears it, so a returning user starts the clock again.
        await s.execute(text(f"UPDATE users SET inactivity_notice_at = NULL WHERE inactivity_notice_at IS NOT NULL AND {seen} > inactivity_notice_at"))
        deleted = (
            await s.execute(
                text(f"DELETE FROM users WHERE NOT is_demo AND inactivity_notice_at < :n AND {seen} < :t"),
                {"n": now - timedelta(days=settings.inactive_notice_days), "t": now - delete_after},
            )
        ).rowcount or 0
    for _, email in to_warn:
        await send_system_email(
            email,
            "Your JobPilot account will be deleted in 30 days",
            "You haven't used JobPilot for 11 months. To protect your data, we delete accounts after a year without use.\n\n"
            f"Sign in at {settings.app_url} before then to keep it, or do nothing and everything will be deleted.",
        )
    return {"inactive_warned": len(to_warn), "inactive_deleted": deleted}

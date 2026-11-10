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
    log.info("retention.sweep", **out)
    return out

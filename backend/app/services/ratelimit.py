"""Fixed-window rate limits kept in Postgres, so they hold across every API replica (no Redis needed)."""

from datetime import UTC, datetime

from fastapi import HTTPException, Request, status
from sqlalchemy import text

from app.config import settings
from app.db import session_scope

# name -> (requests, window seconds)
LIMITS: dict[str, tuple[int, int]] = {
    "login": (10, 15 * 60),
    "register": (5, 60 * 60),
    "password_reset": (5, 60 * 60),
    "resume_upload": (20, 60 * 60),
    "run": (30, 60 * 60),
    "demo": (10, 60 * 60),
    "mail_verify": (10, 60 * 60),
    "evidence": (20, 60 * 60),
    "whatsapp": (5, 60 * 60),
    "rights": (10, 24 * 60 * 60),
    "scam_check": (30, 60 * 60),
    "resume_tools": (60, 60 * 60),
    "interview": (30, 60 * 60),
    "interview_report": (20, 60 * 60),
    "code_review": (60, 60 * 60),
    "payments_sync": (60, 60 * 60),
    "stt": (150, 60 * 60),
}


def client_ip(request: Request) -> str:
    # Behind the Next.js proxy / Render's load balancer the first X-Forwarded-For hop is the browser.
    fwd = request.headers.get("x-forwarded-for", "")
    return (fwd.split(",")[0].strip() if fwd else "") or (request.client.host if request.client else "unknown")


async def hit(name: str, key: str) -> None:
    """Count one request for `key` under limit `name`; 429 with Retry-After once it's used up."""
    if not settings.rate_limits_enabled:
        return
    limit, window = LIMITS[name]
    now = datetime.now(UTC)
    start = datetime.fromtimestamp(int(now.timestamp()) // window * window, UTC)
    async with session_scope() as s:
        count = (
            await s.execute(
                text(
                    "INSERT INTO rate_limits (key, window_start, count) VALUES (:k, :w, 1) "
                    "ON CONFLICT (key, window_start) DO UPDATE SET count = rate_limits.count + 1 RETURNING count"
                ),
                {"k": f"{name}:{key}"[:300], "w": start},
            )
        ).scalar_one()
    if count > limit:
        retry = int(start.timestamp()) + window - int(now.timestamp())
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"Too many attempts. Try again in {max(1, retry // 60)} minute(s).",
            headers={"Retry-After": str(max(1, retry))},
        )

"""Weekly refresh of linked proof-of-skills profiles (GitHub, Codeforces), so a shared proof page stays current."""

from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select, text

from app.db import session_scope
from app.logging import log
from app.models import Profile
from app.services.evidence import EvidenceError, fetch_codeforces, fetch_github
from app.sources.base import USER_AGENT

BATCH = 200  # per day: well inside GitHub's limits with a token (5,000 requests / hour)


async def refresh_evidence() -> int:
    cutoff = (datetime.now(UTC) - timedelta(days=7)).isoformat()
    refreshed = 0
    async with session_scope() as s:
        if not (await s.execute(text("SELECT pg_try_advisory_xact_lock(724007)"))).scalar():
            return 0
        profiles = (await s.execute(select(Profile).where(Profile.evidence.has_key("github") | Profile.evidence.has_key("codeforces")).limit(BATCH * 3))).scalars().all()
        async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT}, follow_redirects=True) as client:
            for p in profiles:
                if refreshed >= BATCH:
                    break
                ev = dict(p.evidence or {})
                changed = False
                for key, fetch, ident in (("github", fetch_github, "username"), ("codeforces", fetch_codeforces, "handle")):
                    block = ev.get(key)
                    if not block or (block.get("fetched_at") or "") > cutoff:
                        continue
                    try:
                        fresh = await fetch(client, block[ident])
                    except (EvidenceError, httpx.HTTPError, ValueError) as exc:
                        log.warning("evidence.refresh_failed", source=key, error=str(exc)[:200])
                        continue
                    if key == "github":  # ownership was checked once; keep it while the account is the same
                        fresh["verified"], fresh["verified_at"] = block.get("verified", False), block.get("verified_at")
                    ev[key], changed = fresh, True
                if changed:
                    p.evidence = ev
                    refreshed += 1
    return refreshed

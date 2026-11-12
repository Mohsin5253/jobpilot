"""Domain age from public RDAP (cached a day per domain, through the egress gate). Very new domains are a scam signal
for both Scam Shield and the pipeline's Verifier."""

import time
from datetime import UTC, datetime

import httpx

from app.config import settings
from app.safety import egress

_cache: dict[str, tuple[float, int | None]] = {}


async def domain_age(domain: str) -> int | None:
    """Days since registration, or None when unknown."""
    hit = _cache.get(domain)
    if hit and hit[0] > time.monotonic():
        return hit[1]
    age = None
    try:
        async with egress.client("rdap", timeout=2, follow_redirects=True) as c:
            r = await c.get(f"https://rdap.org/domain/{domain}")
        if r.status_code == 200:
            for ev in r.json().get("events", []):
                if ev.get("eventAction") == "registration":
                    age = (datetime.now(UTC) - datetime.fromisoformat(ev["eventDate"].replace("Z", "+00:00"))).days
    except (httpx.HTTPError, ValueError, KeyError):
        pass
    _cache[domain] = (time.monotonic() + 86400, age)
    return age


async def ages_for(domains: list[str], limit: int = 10) -> dict[str, int]:
    import asyncio

    if not settings.scam_rdap_enabled:
        return {}
    uniq = list(dict.fromkeys(d for d in domains if d))[:limit]
    found = await asyncio.gather(*(domain_age(d) for d in uniq))
    return {d: a for d, a in zip(uniq, found, strict=True) if a is not None}

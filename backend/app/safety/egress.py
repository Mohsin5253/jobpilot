"""The egress gate: every outbound HTTP request JobPilot makes (job sources, career pages, link checks, contacts,
proof-page data, Gmail, Razorpay, WhatsApp) goes through `client(purpose)`, whose request hook asks the policy:

1. Denylist first, always: LinkedIn and the never-used job boards, and government portals (linked, never fetched),
   on every redirect hop too. Private, loopback and link-local addresses are refused (no SSRF).
2. Allowlist by purpose: fixed services may reach only their own hosts. Purposes that must reach a company's own
   site (career pages, apply-link checks, contact pages, a pasted non-job-board link) may reach any other public host.
3. Rate limits, shared by every API replica through Postgres: the per-minute ceilings published on the Trust page
   (from the `sources` table), and 1 request a minute per domain for career pages.

A denied request raises EgressDenied, an httpx.HTTPError, so callers treat it like a failed fetch."""

import asyncio
import contextvars
import ipaddress
import time
from datetime import UTC, datetime
from urllib.parse import urlparse

import httpx

from app.config import settings
from app.logging import log

# Never fetched, whatever asks: ToS-forbidden boards, and government portals (we only link to them).
DENY = (
    "linkedin.com", "lnkd.in", "glassdoor.com", "glassdoor.co.in", "indeed.com", "indeed.co.in", "internshala.com",
    "naukri.com", "unstop.com", "wellfound.com", "angel.co", "foundit.in", "shine.com",
    "gov.in", "nic.in", "mca.gov.in", "aicte-india.org",
)

# Fixed services: host -> (rate bucket from the `sources` table or a fixed one, requests per minute).
SOURCE_HOSTS: dict[str, str] = {
    "boards-api.greenhouse.io": "greenhouse",
    "api.greenhouse.io": "greenhouse",
    "api.lever.co": "lever",
    "api.ashbyhq.com": "ashby",
    "raw.githubusercontent.com": "github_listings",
    "www.themuse.com": "themuse",
    "remotive.com": "remotive",
    "jobicy.com": "jobicy",
    "api.adzuna.com": "adzuna",
    "jsearch.p.rapidapi.com": "jsearch",
    "api.openwebninja.com": "jsearch",
}
# The published ceilings (seeded in the `sources` table, shown on /trust). Read from the table when it's reachable.
DEFAULT_RATES = {"greenhouse": 30, "lever": 30, "ashby": 30, "github_listings": 1, "themuse": 4, "remotive": 1, "jobicy": 1, "adzuna": 1, "jsearch": 1, "career_page": 1}

FIXED: dict[str, set[str]] = {
    "sources": set(SOURCE_HOSTS),
    "gmail": {"oauth2.googleapis.com", "gmail.googleapis.com", "www.googleapis.com", "openidconnect.googleapis.com", "accounts.google.com"},
    "razorpay": {"api.razorpay.com", "rzp.io"},
    "whatsapp": {"graph.facebook.com"},
    "evidence": {"api.github.com", "github.com", "codeforces.com"},
    "contacts": {"api.hunter.io"},
}
# Purposes that reach a company's (or a pasted link's) own public site.
OPEN = {"career_page", "link_check", "contacts", "evidence", "ingest", "scam_shield", "rdap", "razorpay", "self"}

_purpose: contextvars.ContextVar[str | None] = contextvars.ContextVar("egress_purpose", default=None)


class EgressDenied(httpx.HTTPError):
    def __init__(self, url: str, rule: str):
        super().__init__(f"Request to {host_of(url) or url} refused ({rule})")
        self.rule = rule


def host_of(url: str) -> str:
    try:
        return (urlparse(url if "://" in url else f"https://{url}").hostname or "").lower().rstrip(".")
    except ValueError:
        return ""


def _matches(host: str, domain: str) -> bool:
    h = host.removeprefix("www.")
    return h == domain or h.endswith("." + domain)


def denied(url: str) -> bool:
    h = host_of(url)
    return any(_matches(h, d) for d in DENY)


def _private(host: str) -> bool:
    if host in ("localhost",) or host.endswith((".local", ".internal", ".localhost")):
        return True
    try:
        return not ipaddress.ip_address(host.strip("[]")).is_global
    except ValueError:
        return False


def check(url: str, purpose: str) -> tuple[bool, str]:
    """(allowed, rule). Pure: no I/O."""
    u = urlparse(url)
    host = host_of(url)
    if u.scheme not in ("http", "https") or not host:
        return False, "bad_url"
    if any(_matches(host, d) for d in DENY):
        return False, "denylist"
    if _private(host):
        return False, "private_address"
    if host in FIXED.get(purpose, set()):
        return True, f"allow:{purpose}"
    if purpose in OPEN:
        return True, f"allow_open:{purpose}"
    return False, "not_on_allowlist"


# ---------- shared rate limits (fixed one-minute windows in Postgres) ----------

_rates: tuple[float, dict[str, int]] = (0.0, {})


async def _rate(bucket: str) -> int:
    global _rates
    if _rates[0] < time.monotonic():
        rates = dict(DEFAULT_RATES)
        try:
            from sqlalchemy import text

            from app.db import session_scope

            async with session_scope() as s:
                for sid, per_min in (await s.execute(text("SELECT id, rate_limit_per_min FROM sources"))).all():
                    if per_min and per_min > 0:
                        rates[sid] = per_min
        except Exception:  # noqa: BLE001 - the published defaults apply
            pass
        _rates = (time.monotonic() + 300, rates)
    return _rates[1].get(bucket, 0)


async def _take(key: str, per_min: int) -> bool:
    from sqlalchemy import text

    from app.db import session_scope

    now = datetime.now(UTC)
    window = now.replace(second=0, microsecond=0)
    async with session_scope() as s:
        got = (
            await s.execute(
                text(
                    "INSERT INTO rate_limits (key, window_start, count) VALUES (:k, :w, 1) "
                    "ON CONFLICT (key, window_start) DO UPDATE SET count = rate_limits.count + 1 "
                    "WHERE rate_limits.count < :n RETURNING count"
                ),
                {"k": f"egress:{key}"[:300], "w": window, "n": per_min},
            )
        ).scalar_one_or_none()
    return got is not None


async def throttle(bucket: str, key: str | None = None, max_wait_s: float | None = None) -> None:
    """Wait for a slot in this minute's bucket (shared across replicas); refuse if none frees up in time."""
    if not settings.egress_throttle_enabled:
        return
    per_min = await _rate(bucket)
    if per_min <= 0:
        return
    deadline = time.monotonic() + (settings.egress_max_wait_s if max_wait_s is None else max_wait_s)
    while True:
        if await _take(key or bucket, per_min):
            return
        wait = 60.5 - datetime.now(UTC).second
        if time.monotonic() + wait > deadline:
            raise EgressDenied(key or bucket, f"rate_limit:{bucket}")
        await asyncio.sleep(wait)


# ---------- the client ----------


class purpose:
    """`with egress.purpose("career_page"):` marks requests made inside as that purpose (for a shared client)."""

    def __init__(self, name: str):
        self.name, self.token = name, None

    def __enter__(self):
        self.token = _purpose.set(self.name)
        return self

    def __exit__(self, *exc):
        _purpose.reset(self.token)


async def gate(url: str, default_purpose: str) -> None:
    p = _purpose.get() or default_purpose
    ok, rule = check(url, p)
    if not ok:
        log.info("policy.decision", actor=p, action="http.fetch", allow=False, rule=rule, host=host_of(url))
        raise EgressDenied(url, rule)
    host = host_of(url)
    if p == "sources" and host in SOURCE_HOSTS:
        await throttle(SOURCE_HOSTS[host])
    elif p == "career_page" and urlparse(url).path != "/robots.txt":
        # One page request a minute per domain; a domain fetched this minute is skipped, not waited for.
        from app.services.scam_shield import registrable

        await throttle("career_page", f"career_page:{registrable(host.removeprefix('www.'))}", max_wait_s=0)


def client(default_purpose: str, **kw) -> httpx.AsyncClient:
    """An httpx client whose every request (redirect hops included) passes the gate."""

    async def hook(request: httpx.Request) -> None:
        await gate(str(request.url), default_purpose)

    hooks = kw.pop("event_hooks", {}) or {}
    hooks = {**hooks, "request": [hook, *hooks.get("request", [])]}
    return httpx.AsyncClient(event_hooks=hooks, **kw)

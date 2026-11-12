"""Researcher: keeps widening where the Scout looks.

Every research pass (at most once per settings.research_cooldown_hours per user) it gathers candidate
companies three ways:
  * the LLM suggests companies that hire people with your profile (tech and non-tech), in India/remote;
  * companies seen in postings from the public feeds (The Muse, Remotive, Jobicy, Adzuna);
  * a curated catalog of companies known to run public career boards.
Each candidate is checked against the public Greenhouse, Lever and Ashby job-board APIs. A board is
added to your search only if it is live and lists roles that pass your filters (early-career, role
type, India / remote) - or has several India/remote roles and is worth watching. Everything it adds is
shown in Settings and can be removed.
"""

import asyncio
import re
import uuid
from datetime import UTC, datetime, timedelta

import httpx
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.agents.common import PipelineState, agent_step, bump_stats, ctx_of, load_profile
from app.config import settings
from app.db import session_scope
from app.llm import LLMOutputError, LLMUnavailable, get_llm
from app.logging import log
from app.models import BoardProbe, Job, Notification, Profile
from app.schemas import Preferences, ResumeData
from app.sources.base import USER_AGENT
from app.sources.providers import title_location_ok
from app.safety import egress

# Companies with public boards worth checking even before the LLM weighs in (Indian startups and
# global companies with India offices, across engineering, data, marketing, sales, ops, HR, finance).
CATALOG = """razorpay groww phonepe meesho swiggy zomato cred zeta paytm dream11 sharechat slice zepto
postman browserstack freshworks chargebee druva rubrik inmobi sprinklr mindtickle innovaccer hasura
juspay setu smallcase upstox cars24 spinny practo unacademy upgrad scaler eightfold sarvam krutrim
atlassian stripe databricks mongodb cloudflare elastic twilio gitlab notion figma canva airbnb uber
coinbase rippling deel hackerrank thoughtspot nutanix samsara intercom zapier ola flipkart myntra nykaa
lenskart urbancompany dunzo khatabook jar fi bharatpe cleartax policybazaar delhivery shiprocket""".split()

PROVIDERS = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs",
    "lever": "https://api.lever.co/v0/postings/{slug}?mode=json",
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{slug}",
}
_SUFFIX = re.compile(r"\b(inc|ltd|llc|limited|pvt|private|technologies|technology|labs|software|corp|corporation|co|india|group|careers)\b", re.I)


class CompanyIdeas(BaseModel):
    companies: list[str] = Field(description="Company names only, no descriptions")


SYSTEM = """You are a career researcher for a student in India looking for internships and entry-level roles.
Suggest real companies that are likely to hire someone with this profile, in India or remotely, and that
publish jobs on public career boards (many startups use Greenhouse, Lever or Ashby). Mix well-known and
lesser-known companies. Cover the role types requested. Return company names only."""


def slug_variants(name: str) -> list[str]:
    base = _SUFFIX.sub(" ", name.lower())
    words = re.findall(r"[a-z0-9]+", base)
    if not words:
        return []
    variants = ["".join(words), "-".join(words)]
    if len(words) > 1:
        variants.append(words[0])
    return list(dict.fromkeys(v for v in variants if len(v) >= 2))


def _titles_locations(provider: str, data) -> list[tuple[str, str, bool]]:
    if provider == "greenhouse":
        return [(j.get("title", ""), (j.get("location") or {}).get("name", ""), "remote" in ((j.get("location") or {}).get("name", "")).lower()) for j in data.get("jobs", [])]
    if provider == "lever":
        return [
            (j.get("text", ""), (j.get("categories") or {}).get("location", "") or "", j.get("workplaceType") == "remote")
            for j in (data if isinstance(data, list) else [])
        ]
    return [
        (j.get("title", "") + (" (Intern)" if j.get("employmentType") == "Intern" else ""), j.get("location", "") or "", bool(j.get("isRemote")))
        for j in data.get("jobs", [])
        if j.get("isListed", True)
    ]


PROBE_TTL = {"board": timedelta(days=2), "none": timedelta(days=14)}


async def board_roles(client: httpx.AsyncClient, slug: str) -> dict | None:
    """{provider, token, roles: [(title, location, remote)]} for the first provider with a live board, else None."""
    for provider, url in PROVIDERS.items():
        try:
            r = await client.get(url.format(slug=slug), timeout=12)
            if r.status_code != 200:
                continue
            roles = _titles_locations(provider, r.json())
        except (httpx.HTTPError, ValueError):
            continue
        if roles:
            return {"provider": provider, "token": slug, "roles": roles[:400]}
    return None


async def cached_board_roles(client: httpx.AsyncClient, slugs: list[str]) -> dict[str, dict | None]:
    """Board lookups shared across users: a company checked for anyone in the last few days isn't probed again."""
    now = datetime.now(UTC)
    async with session_scope() as s:
        cached = {b.slug: b for b in (await s.execute(select(BoardProbe).where(BoardProbe.slug.in_(slugs)))).scalars()}
    out: dict[str, dict | None] = {}
    todo = []
    for slug in slugs:
        hit = cached.get(slug)
        if hit and now - hit.checked_at < PROBE_TTL["board" if hit.result else "none"]:
            out[slug] = hit.result
        else:
            todo.append(slug)
    sem = asyncio.Semaphore(10)

    async def one(slug: str) -> dict | None:
        async with sem:
            return await board_roles(client, slug)

    fresh = await asyncio.gather(*(one(slug) for slug in todo))
    if todo:
        async with session_scope() as s:
            stmt = insert(BoardProbe).values([{"slug": slug, "result": res, "checked_at": now} for slug, res in zip(todo, fresh)])
            await s.execute(stmt.on_conflict_do_update(index_elements=["slug"], set_={"result": stmt.excluded.result, "checked_at": now}))
    out.update(zip(todo, fresh))
    return out


def evaluate(board: dict | None, prefs: Preferences) -> dict | None:
    """Worth adding for this user: roles that pass their filters, or several roles they could take at all."""
    if not board:
        return None
    roles = [tuple(r) for r in board["roles"]]
    fits = sum(title_location_ok(t, loc, rem, prefs) for t, loc, rem in roles)
    # Roles you could take at all (India, or remote that's open to India) - any level, any track.
    reachable = prefs.model_copy(update={"internships_only": False, "tracks": ["technical", "non_technical"]})
    local = sum(title_location_ok(t, loc, rem, reachable) for t, loc, rem in roles)
    if fits == 0 and local < 3:
        return None
    return {"provider": board["provider"], "token": board["token"], "roles": len(roles), "fits": fits, "local": local}


async def probe(client: httpx.AsyncClient, provider: str, slug: str, prefs: Preferences) -> dict | None:
    """One provider, uncached (kept for callers that check a specific board)."""
    try:
        r = await client.get(PROVIDERS[provider].format(slug=slug), timeout=12)
        if r.status_code != 200:
            return None
        roles = _titles_locations(provider, r.json())
    except (httpx.HTTPError, ValueError):
        return None
    return evaluate({"provider": provider, "token": slug, "roles": roles}, prefs) if roles else None


async def suggest_companies(resume: ResumeData, prefs: Preferences, state: PipelineState) -> list[str]:
    tracks = " and ".join("technical" if t == "technical" else "non-technical" for t in prefs.tracks)
    try:
        out = await get_llm().structured(
            agent="researcher",
            tier="fast",
            system=SYSTEM,
            prompt=(
                f"Role types: {tracks}. Locations: {', '.join(prefs.locations) or 'any'}.\n"
                f"Skills: {', '.join(resume.skills[:30])}\n"
                f"Background: {resume.summary[:400] or (resume.experience[0].title if resume.experience else '')}\n"
                "Suggest 25 companies."
            ),
            schema=CompanyIdeas,
            ctx=ctx_of(state),
            max_tokens=2000,
        )
        return [c.strip() for c in out.companies if c.strip()][:30]
    except (LLMUnavailable, LLMOutputError):
        return []


async def run_researcher(state: PipelineState) -> dict:
    async with agent_step(state, "researcher") as step:
        profile, resume, prefs = await load_profile(state["user_id"])
        research = dict(profile.research or {})
        now = datetime.now(UTC)
        last = research.get("last_research_at")
        if not settings.researcher_enabled or not prefs.research_enabled:
            step.detail = "Research is turned off in Settings"
            return {"done": ["researcher"]}
        if last and not state.get("force_research") and now - datetime.fromisoformat(last) < timedelta(hours=settings.research_cooldown_hours):
            step.detail = f"Searched for new companies {int((now - datetime.fromisoformat(last)).total_seconds() // 3600)}h ago; next pass later today"
            return {"done": ["researcher"]}

        known = {t.lower() for t in [*prefs.greenhouse_boards, *prefs.lever_boards, *prefs.ashby_boards]}
        checked = set(research.get("checked", []))

        ideas = await suggest_companies(resume, prefs, state)
        async with session_scope() as s:
            feed_companies = (
                await s.execute(
                    select(Job.company)
                    .where(Job.source.in_(["themuse", "remotive", "jobicy", "adzuna"]), Job.fetched_at >= now - timedelta(days=14))
                    .distinct()
                    .limit(60)
                )
            ).scalars().all()

        names = list(dict.fromkeys([*ideas, *feed_companies, *CATALOG]))
        slugs: list[str] = []
        for name in names:
            for slug in slug_variants(name):
                if slug not in known and slug not in checked and slug not in slugs:
                    slugs.append(slug)
        slugs = slugs[: settings.research_max_candidates * 2]

        async with egress.client("sources", headers={"User-Agent": USER_AGENT}) as client:
            boards = await cached_board_roles(client, slugs)
        hits = [h for h in (evaluate(boards.get(slug), prefs) for slug in slugs) if h]

        # Persist: new boards into preferences, the research log and the checked set into profile.research. The Scout
        # (running in parallel) and the student (editing Settings) may have changed this record since we read it, so
        # re-read it under a row lock and merge only what the Researcher adds.
        added = [{**h, "company": h["token"].replace("-", " ").title(), "at": now.isoformat()} for h in hits]
        async with session_scope() as s:
            row = (await s.execute(select(Profile).where(Profile.id == profile.id).with_for_update())).scalar_one()
            current = Preferences.model_validate(row.preferences or {})
            lists = {"greenhouse": list(current.greenhouse_boards), "lever": list(current.lever_boards), "ashby": list(current.ashby_boards)}
            for h in hits:
                if h["token"] not in lists[h["provider"]]:
                    lists[h["provider"]].append(h["token"])
            row.preferences = current.model_copy(update={"greenhouse_boards": lists["greenhouse"], "lever_boards": lists["lever"], "ashby_boards": lists["ashby"]}).model_dump()
            latest = dict(row.research or {})
            latest.update(
                last_research_at=now.isoformat(),
                checked=list(dict.fromkeys([*latest.get("checked", []), *slugs]))[-800:],
                added=[*latest.get("added", []), *added][-200:],
                ideas=ideas[:30],
            )
            row.research = latest
            if hits:
                fits = sum(h["fits"] for h in hits)
                s.add(
                    Notification(
                        user_id=uuid.UUID(state["user_id"]),
                        kind="research",
                        title=f"Researcher found {len(hits)} new compan{'y' if len(hits) == 1 else 'ies'} hiring",
                        body=", ".join(a["company"] for a in added[:8]) + (f" — {fits} open role(s) fit your filters" if fits else ""),
                    )
                )

        log.info("researcher.done", ideas=len(ideas), probed=len(slugs), added=len(hits))
        step.detail = (
            f"Checked {len(slugs)} company boards ({len(ideas)} suggested for your profile) · "
            + (f"added {len(hits)}: {', '.join(a['company'] for a in added[:6])}" if hits else "no new boards with matching roles")
        )
        await bump_stats(state["run_id"], boards_added=len(hits))
        return {"done": ["researcher"]}

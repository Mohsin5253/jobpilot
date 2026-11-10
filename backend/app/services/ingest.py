"""Shared ingestion: job sources are fetched once for everyone, not once per user.

Every company board (greenhouse/stripe), public feed and aggregator search (adzuna/"data analyst intern")
that any active user wants is a row in `source_targets`, with how many users want it (`demand`) and the
widest filter any of them needs (`fetch_prefs`). Each minute, every worker leases a slice of due targets
(UPDATE ... FOR UPDATE SKIP LOCKED, so replicas split the work and never fetch the same thing twice),
fetches them, stores the postings once in the shared index and then wakes only the users a new job is
close to (one pgvector query), whose agents score it within seconds.

Quota-limited APIs (JSearch, Adzuna) have one budget for the whole service: a "*" row per source is the
budget clock, and each tick it allows one request spent on the least recently fetched, most wanted search.

Outbound requests therefore grow with the number of distinct boards and searches (hundreds), not with
users x sources.
"""

import asyncio
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert

from app.config import settings
from app.db import session_scope
from app.embeddings import get_embedder
from app.logging import log
from app.models import AgentRun, Job, Profile, SourceTarget, User
from app.schemas import Preferences
from app.services.job_store import job_as_posting, store_postings
from app.sources.authenticity import FIRST_PARTY, looks_legit
from app.sources.base import USER_AGENT, Posting, is_relevant
from app.sources.providers import ALL_SOURCES

SOURCES = {s.name: s for s in ALL_SOURCES}
BOARD_FIELDS = {"greenhouse": "greenhouse_boards", "lever": "lever_boards", "ashby": "ashby_boards"}
FEED = "feed"  # the single target of a public feed
BUDGET = "*"  # a quota source's budget clock
LEASE = timedelta(minutes=5)  # a crashed worker's claimed targets come back after this
SYNC_EVERY_S = 300
ACTIVE_DAYS = 30  # users who haven't opened the app in a month stop driving fetches
# None until the first tick. Not 0.0: time.monotonic() counts from boot, so on a machine up for under
# SYNC_EVERY_S (a fresh CI runner) a 0.0 start would skip the first sync.
_last_sync: float | None = None


def _quota(name: str) -> bool:
    return bool(getattr(SOURCES.get(name), "quota_limited", False))


def wanted_targets(prefs: Preferences, skills: list[str] | None) -> list[tuple[str, str]]:
    """Everything this user's settings ask the sources for."""
    out: list[tuple[str, str]] = []
    for src in ALL_SOURCES:
        if not src.enabled(prefs):
            continue
        if src.name in BOARD_FIELDS:
            out += [(src.name, t.strip().lower()) for t in getattr(prefs, BOARD_FIELDS[src.name]) if t.strip()]
        elif hasattr(src, "queries"):
            out += [(src.name, q) for q in src.queries(prefs, skills)]
        else:
            out.append((src.name, FEED))
    return list(dict.fromkeys(out))


def widest(prefs_list: list[Preferences]) -> dict:
    """One fetch filter that keeps every posting at least one of these users could want; each user's own
    filter (keywords, exact locations, freshness) is applied when their Scout reads the index."""
    any_location = any(not p.locations for p in prefs_list)
    return {
        "keywords": [],
        "locations": [] if any_location else sorted({loc for p in prefs_list for loc in p.locations}),
        "tracks": sorted({t for p in prefs_list for t in p.tracks}),
        "internships_only": all(p.internships_only for p in prefs_list),
        "remote_ok": any(p.remote_ok for p in prefs_list),
        "max_age_days": max(p.max_age_days for p in prefs_list),
        "max_jobs_per_source": max(p.max_jobs_per_source for p in prefs_list),
        "adzuna_country": prefs_list[0].adzuna_country,
        "public_job_feeds": True,
        "greenhouse_boards": [],
        "lever_boards": [],
        "ashby_boards": [],
    }


async def _upsert_targets(s, wants: dict[tuple[str, str], list[Preferences]], replace_demand: bool) -> list[uuid.UUID]:
    if not wants:
        return []
    rows = [{"id": uuid.uuid4(), "source": src, "target": tgt[:300], "demand": len(ps), "fetch_prefs": widest(ps)} for (src, tgt), ps in wants.items()]
    # Each quota source gets its budget clock.
    rows += [
        {"id": uuid.uuid4(), "source": src, "target": BUDGET, "demand": 0, "fetch_prefs": {}}
        for src in {src for src, _ in wants if _quota(src)}
    ]
    ids: list[uuid.UUID] = []
    for i in range(0, len(rows), 500):
        stmt = insert(SourceTarget).values(rows[i : i + 500])
        if replace_demand:
            set_ = {"demand": stmt.excluded.demand, "fetch_prefs": stmt.excluded.fetch_prefs}
        else:  # one user's view: never lower what the full sync computed
            set_ = {"demand": func.greatest(SourceTarget.demand, stmt.excluded.demand)}
        ids += list((await s.execute(stmt.on_conflict_do_update(constraint="uq_source_target", set_=set_).returning(SourceTarget.id))).scalars())
    return ids


async def sync_targets() -> int:
    """Rebuild every target's demand and fetch filter from all active users' settings (set-based, cheap)."""
    async with session_scope() as s:
        if not (await s.execute(text("SELECT pg_try_advisory_xact_lock(724004)"))).scalar():
            return 0
        since = datetime.now(UTC) - timedelta(days=ACTIVE_DAYS)
        rows = (
            await s.execute(
                select(Profile.preferences, Profile.resume["skills"])
                .join(User, User.id == Profile.user_id)
                .where(Profile.resume_text != "", User.is_demo.is_(False), func.coalesce(User.last_seen_at, User.created_at) >= since)
            )
        ).all()
        wants: dict[tuple[str, str], list[Preferences]] = defaultdict(list)
        for prefs_raw, skills in rows:
            prefs = Preferences.model_validate(prefs_raw or {})
            if not (prefs.research_enabled or prefs.daily_runs_enabled):
                continue
            for key in wanted_targets(prefs, skills if isinstance(skills, list) else None):
                wants[key].append(prefs)
        ids = await _upsert_targets(s, wants, replace_demand=True)
        await s.execute(update(SourceTarget).where(SourceTarget.id.not_in(ids), SourceTarget.demand > 0).values(demand=0))
    return len(ids)


async def ensure_user_targets(prefs: Preferences, skills: list[str] | None) -> list[uuid.UUID]:
    """A user's targets exist right away (a new user's first run needn't wait for the next sync)."""
    wants = {key: [prefs] for key in wanted_targets(prefs, skills)}
    async with session_scope() as s:
        return await _upsert_targets(s, wants, replace_demand=False)


@dataclass
class Claimed:
    id: uuid.UUID
    source: str
    target: str
    fetch_prefs: dict
    failures: int


async def claim_due(limit: int, only: list[uuid.UUID] | None = None) -> list[Claimed]:
    """Lease due targets. Safe to call from any number of workers at once."""
    now = datetime.now(UTC)
    enabled = {name for name, src in SOURCES.items() if src.enabled(Preferences())} | set(BOARD_FIELDS)
    free = [n for n in enabled if not _quota(n)]
    claimed: list[Claimed] = []
    async with session_scope() as s:
        inner = (
            select(SourceTarget.id)
            .where(SourceTarget.next_due_at <= now, SourceTarget.demand > 0, SourceTarget.source.in_(free), SourceTarget.target != BUDGET)
            .order_by(SourceTarget.next_due_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        if only is not None:
            inner = inner.where(SourceTarget.id.in_(only))
        rows = (
            await s.execute(
                update(SourceTarget)
                .where(SourceTarget.id.in_(inner.scalar_subquery()))
                .values(next_due_at=now + LEASE)
                .returning(SourceTarget.id, SourceTarget.source, SourceTarget.target, SourceTarget.fetch_prefs, SourceTarget.failures)
            )
        ).all()
        claimed += [Claimed(*r) for r in rows]

        for name in (n for n in enabled if _quota(n)):
            gap = timedelta(minutes=SOURCES[name].min_interval_minutes)
            # Take the budget clock: only one worker can, and only once per gap for the whole service.
            got = (
                await s.execute(
                    update(SourceTarget)
                    .where(SourceTarget.source == name, SourceTarget.target == BUDGET, SourceTarget.next_due_at <= now)
                    .values(next_due_at=now + gap)
                    .returning(SourceTarget.id)
                )
            ).first()
            if not got:
                continue
            pick = (
                select(SourceTarget)
                .where(SourceTarget.source == name, SourceTarget.target != BUDGET, SourceTarget.demand > 0)
                .order_by(SourceTarget.last_fetched_at.asc().nulls_first(), SourceTarget.demand.desc())
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            if only is not None:
                pick = pick.where(SourceTarget.id.in_(only))
            row = (await s.execute(pick)).scalar_one_or_none()
            if row is None:  # nothing to spend it on: give the budget back
                await s.execute(update(SourceTarget).where(SourceTarget.id == got.id).values(next_due_at=now))
                continue
            row.next_due_at = now + LEASE
            claimed.append(Claimed(row.id, row.source, row.target, dict(row.fetch_prefs or {}), row.failures))
    return claimed


@dataclass
class IngestResult:
    report: dict[str, str] = field(default_factory=dict)  # per source, e.g. "greenhouse: 6/11 relevant"
    fetched: int = 0
    inserted_ids: list[uuid.UUID] = field(default_factory=list)
    merged: int = 0
    dead: int = 0


async def _fetch_one(client: httpx.AsyncClient, c: Claimed, now: datetime) -> tuple[list[Posting], int, int]:
    src = SOURCES[c.source]
    prefs = Preferences.model_validate(c.fetch_prefs or {})
    if c.source in BOARD_FIELDS:
        prefs = prefs.model_copy(update={BOARD_FIELDS[c.source]: [c.target]})
    raw = await (src.fetch(client, prefs, c.target) if hasattr(src, "queries") else src.fetch(client, prefs))
    relevant = [p for p in raw if p.title and is_relevant(p, prefs, now)]
    legit = [p for p in relevant if c.source in FIRST_PARTY or looks_legit(p)[0]]
    return legit[: prefs.max_jobs_per_source], len(raw), len(relevant) - len(legit)


async def ingest(claimed: list[Claimed]) -> IngestResult:
    """Fetch the leased targets, store what they list once, and set each target's next due time."""
    out = IngestResult()
    if not claimed:
        return out
    now = datetime.now(UTC)
    sem = asyncio.Semaphore(settings.ingest_concurrency)

    async def guarded(c: Claimed):
        async with sem:
            try:
                return await _fetch_one(client, c, now)
            except Exception as exc:  # one broken board must not sink the rest
                log.warning("ingest.target_failed", source=c.source, target=c.target, error=repr(exc)[:300])
                return exc

    async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT}, follow_redirects=True) as client:
        results = await asyncio.gather(*(guarded(c) for c in claimed))

    postings: list[Posting] = []
    per_source: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0, 0])  # kept, listed, suspicious, failed
    errors: dict[str, str] = {}
    updates = []
    for c, res in zip(claimed, results):
        gap = timedelta(minutes=SOURCES[c.source].min_interval_minutes)
        if isinstance(res, BaseException):
            per_source[c.source][3] += 1
            errors[c.source] = type(res).__name__
            # Back off a broken board (10 min, doubling, at most 6 h); quota targets wait for the budget clock.
            next_due = now + (LEASE if _quota(c.source) else min(timedelta(minutes=10) * 2 ** min(c.failures, 6), timedelta(hours=6)))
            updates.append({"id": c.id, "next_due_at": next_due, "last_status": f"failed: {type(res).__name__}", "failures": c.failures + 1, "postings": 0})
            continue
        kept, listed, suspicious = res
        stats = per_source[c.source]
        stats[0] += len(kept)
        stats[1] += listed
        stats[2] += suspicious
        postings += kept
        next_due = now + gap if not _quota(c.source) else now + LEASE  # quota targets wait for the budget clock
        updates.append({"id": c.id, "next_due_at": next_due, "last_status": "ok", "failures": 0, "postings": len(kept), "last_fetched_at": now})

    async with session_scope() as s:
        for u in updates:
            await s.execute(update(SourceTarget).where(SourceTarget.id == u.pop("id")).values(**u))

    for name, (kept, listed, suspicious, failed) in per_source.items():
        if failed and not listed and not kept:
            out.report[name] = f"failed: {errors[name]}"
        else:
            out.report[name] = f"{kept}/{listed} relevant" + (f", {suspicious} suspicious dropped" if suspicious else "")
    stored = await store_postings(postings, now)
    out.fetched = len(stored.job_ids)
    out.inserted_ids = stored.inserted_ids
    out.merged = stored.merged
    out.dead = stored.dead
    return out


async def fan_out(job_ids: list[uuid.UUID]) -> int:
    """Wake the agents of users a new job could fit (close to their resume and inside their filters).
    Everyone else is untouched, so 10,000 users cost the same as 10 when a new posting arrives."""
    from app.services.runs import AgeNotConfirmed, enqueue_run

    if not job_ids:
        return 0
    max_dist = get_embedder().max_distance(settings.fanout_min_semantic)
    now = datetime.now(UTC)
    async with session_scope() as s:
        candidates = (
            await s.execute(
                text(
                    """
                    SELECT p.user_id, p.preferences, u.plan FROM profiles p JOIN users u ON u.id = p.user_id
                    WHERE p.embedding IS NOT NULL AND p.resume_text <> '' AND NOT u.is_demo
                      AND COALESCE((p.preferences->>'research_enabled')::boolean, true)
                      AND EXISTS (SELECT 1 FROM jobs j WHERE j.id = ANY(:ids) AND (j.embedding <=> p.embedding) <= :d)
                    """
                ),
                {"ids": job_ids, "d": max_dist},
            )
        ).all()
        if not candidates:
            return 0
        jobs = [job_as_posting(j) for j in (await s.execute(select(Job).where(Job.id.in_(job_ids)))).scalars()]
        recent = dict(
            (
                await s.execute(
                    select(AgentRun.user_id, func.max(AgentRun.created_at))
                    .where(AgentRun.user_id.in_([c.user_id for c in candidates]), AgentRun.trigger == "refresh")
                    .group_by(AgentRun.user_id)
                )
            ).all()
        )
        created = 0
        for user_id, prefs_raw, plan in candidates:
            prefs = Preferences.model_validate(prefs_raw or {})
            if not any(is_relevant(p, prefs, now) for p in jobs):
                continue
            # Free accounts are woken at most every few minutes; Pro instantly.
            wait = max(prefs.refresh_minutes, int(settings.limits(plan)["min_refresh_minutes"]))
            last = recent.get(user_id)
            if last and now - last < timedelta(minutes=wait):
                continue
            try:
                _, was_created = await enqueue_run(s, user_id, trigger="refresh", params={"refresh": True})
            except AgeNotConfirmed:
                continue
            created += was_created
    if created:
        log.info("ingest.fan_out", new_jobs=len(job_ids), runs=created)
    return created


async def ingest_tick() -> dict:
    """Scheduled every minute on every worker: sync demand now and then, fetch what's due, wake users."""
    global _last_sync
    if _last_sync is None or time.monotonic() - _last_sync > SYNC_EVERY_S:
        _last_sync = time.monotonic()
        await sync_targets()
    result = await ingest(await claim_due(settings.ingest_max_targets_per_tick))
    runs = await fan_out(result.inserted_ids)
    if result.report:
        log.info("ingest.tick", stored=result.fetched, new=len(result.inserted_ids), runs=runs, **result.report)
    return {"stored": result.fetched, "new": len(result.inserted_ids), "runs": runs, "report": result.report}

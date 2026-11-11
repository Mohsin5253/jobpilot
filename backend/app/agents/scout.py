"""Scout: hands the Matcher the real, open, relevant jobs this user hasn't seen, from the shared index.

Fetching is shared (app/services/ingest.py): each board, feed and search is fetched once for every user
who wants it, scam-filtered, link-checked, de-duplicated across boards and embedded once. The Scout makes
sure this user's own boards and searches are in that index (fetching any that are due right now, so a new
account's first run finds jobs immediately), then reads it: nearest to the resume first, through this
user's own filters. Refresh runs, started by the ingester when a new job is close to the resume, only
look at jobs indexed since the last look.
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, exists, or_, select

from app.agents.common import PipelineState, agent_step, bump_stats, load_profile
from app.config import settings
from app.db import session_scope
from app.models import Job, JobMatch, Profile
from app.services.ingest import claim_due, ensure_user_targets, ingest
from app.services.job_store import job_as_posting
from app.sources.base import is_relevant

RECHECK_LIMIT = 25  # open matches re-checked when a run finds nothing new
OPEN_DAYS = 4  # a job no source has listed for this long is treated as closed (as on the dashboard)


async def shared_candidates(user_id: uuid.UUID, prefs, profile_vec: list[float], since: datetime | None, now: datetime) -> list[Job]:
    filters = [
        Job.last_seen_at >= now - timedelta(days=OPEN_DAYS),
        or_(Job.link_status.is_(None), Job.link_status != "dead"),
        ~exists().where(and_(JobMatch.job_id == Job.id, JobMatch.user_id == user_id)),
    ]
    if since:
        filters.append(Job.fetched_at > since)
    async with session_scope() as s:
        # Nearest first via the HNSW index, then this user's exact filters in Python.
        rows = (
            await s.execute(select(Job).where(*filters).order_by(Job.embedding.cosine_distance(profile_vec)).limit(settings.scout_candidates * 4))
        ).scalars().all()
    keep = [j for j in rows if is_relevant(job_as_posting(j), prefs, now)]
    return keep[: settings.scout_candidates]


async def run_scout(state: PipelineState) -> dict:
    from app.agents.matcher import ensure_profile_embedding

    async with agent_step(state, "scout") as step:
        profile, resume, prefs = await load_profile(state["user_id"])
        research = dict(profile.research or {})
        now = datetime.now(UTC)
        refresh = bool(state.get("refresh"))

        report: dict[str, str] = {}
        merged = dead = 0
        if not refresh:
            # This user's boards and searches join the shared index; any that are due are fetched now.
            mine = await ensure_user_targets(prefs, resume.skills)
            fetched = await ingest(await claim_due(len(mine) + 2, only=mine))
            report, merged, dead = fetched.report, fetched.merged, fetched.dead

        profile_vec = list(profile.embedding) if profile.embedding is not None else await ensure_profile_embedding(profile.id, resume)
        cursor = research.get("match_cursor")
        since = datetime.fromisoformat(cursor) if refresh and cursor else None
        jobs = await shared_candidates(uuid.UUID(state["user_id"]), prefs, profile_vec, since, now)

        # The Researcher may be writing this record at the same moment (parallel lanes): re-read it under a row lock
        # and change only the Scout's own key, so neither overwrites the other.
        async with session_scope() as s:
            row = (await s.execute(select(Profile).where(Profile.id == profile.id).with_for_update())).scalar_one()
            row.research = {**(row.research or {}), "match_cursor": now.isoformat()}

        new_ids = [str(j.id) for j in jobs]
        # Nothing new: the rest of the crew works on your open matches instead (re-verify links, re-rank against
        # your current resume, tailor and draft whatever is still missing), so every agent still does its job.
        recheck: list[str] = []
        if not refresh:  # also used if the Verifier blocks every new posting
            async with session_scope() as s:
                recheck = [
                    str(m)
                    for m in (
                        await s.execute(
                            select(JobMatch.id)
                            .join(Job, Job.id == JobMatch.job_id)
                            .where(
                                JobMatch.user_id == uuid.UUID(state["user_id"]),
                                JobMatch.stage.in_(["found", "shortlisted"]),
                                Job.last_seen_at >= now - timedelta(days=OPEN_DAYS),
                                or_(Job.link_status.is_(None), Job.link_status != "dead"),
                            )
                            .order_by(JobMatch.score.desc())
                            .limit(RECHECK_LIMIT)
                        )
                    ).scalars()
                ]
        step.detail = (f"{len(new_ids)} new for you" if new_ids else "No new postings") + " from the shared index"
        if recheck and not new_ids:
            step.detail += f" · re-checking your {len(recheck)} open match{'es' if len(recheck) != 1 else ''}"
        if report:
            step.detail += " · " + ", ".join(f"{k}: {v}" for k, v in report.items())
        extras = [f"{merged} merged from other boards" if merged else "", f"{dead} closed listings dropped" if dead else ""]
        if any(extras):
            step.detail += " · " + " · ".join(x for x in extras if x)
        await bump_stats(state["run_id"], jobs_fetched=len(jobs), new_jobs=len(new_ids))
        return {"new_job_ids": new_ids, "recheck_match_ids": recheck, "done": ["scout"]}

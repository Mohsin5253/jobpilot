"""The shared job index: every posting is stored once, however many users or boards it came from.

store_postings() de-duplicates a batch (the same role on LinkedIn and Naukri becomes one job with both
apply links), merges postings already stored from another board, drops aggregator listings whose apply
page is closed, upserts the rest (still listed -> still open) and embeds new ones. It reports which jobs
are brand new to the index, so the ingester can wake up only the users they could fit.
"""

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import func, literal_column, select, tuple_
from sqlalchemy.dialects.postgresql import insert

from app.config import settings
from app.db import session_scope
from app.embeddings import get_embedder
from app.models import Job
from app.skills import extract_skills, job_embedding_text
from app.sources.authenticity import FIRST_PARTY, dedupe_key, verify_postings
from app.sources.base import USER_AGENT, Posting, classify_track
from app.safety import egress

COMPANY_SITE = {"greenhouse": "Company site", "lever": "Company site", "ashby": "Company site"}
_REQUIREMENTS = re.compile(r"requirement|qualification|responsibilit|you will|you'll|skills|what we.re looking for|eligib|must have", re.IGNORECASE)


def ghost_assessment(p: Posting, link_status: str, reposts: int, now: datetime) -> tuple[str, list[str]]:
    """Ghost-job risk: listings that are old but never close, reposted again and again, unverifiable or hollow.
    High-risk jobs are shown with a warning and never get a tailored application."""
    reasons = []
    if p.posted_at and (now - p.posted_at).days > 30:
        reasons.append(f"Posted {(now - p.posted_at).days} days ago and still listed")
    if reposts >= 2:
        reasons.append(f"Reposted {reposts} times in 90 days")
    if link_status == "unverified":
        reasons.append("Apply link couldn't be verified")
    if len(p.description or "") < 400 or not _REQUIREMENTS.search(p.description or ""):
        reasons.append("Description has no real requirements")
    old_and_unverifiable = bool(p.posted_at and (now - p.posted_at).days > 30) and link_status == "unverified"
    risk = "high" if len(reasons) >= 3 or reposts >= 3 or old_and_unverifiable else "medium" if reasons else "low"
    return risk, reasons


@dataclass
class StoreResult:
    job_ids: list[uuid.UUID] = field(default_factory=list)  # every stored (new or still-listed) job
    inserted_ids: list[uuid.UUID] = field(default_factory=list)  # new to the index
    merged: int = 0
    dead: int = 0


def _links(p: Posting) -> list[dict]:
    return p.apply_links or [{"publisher": p.publisher or p.source, "url": p.url, "direct": p.source in FIRST_PARTY}]


async def store_postings(postings: list[Posting], now: datetime) -> StoreResult:
    result = StoreResult()
    postings = list({(p.source, p.external_id): p for p in postings}.values())

    batch: dict[str, Posting] = {}
    for p in postings:
        key = dedupe_key(p.company, p.title, p.location)
        first = batch.get(key)
        if first is None:
            batch[key] = p
            continue
        known = {a.get("url") for a in first.apply_links} | {first.url}
        first.apply_links = _links(first) + [a for a in _links(p) if a.get("url") not in known]
        result.merged += 1
    postings = list(batch.values())
    if not postings:
        return result

    # Cross-board: a role already stored from another source gains this apply link instead of a twin.
    keys = {i: dedupe_key(p.company, p.title, p.location) for i, p in enumerate(postings)}
    async with session_scope() as s:
        existing = {
            j.dedupe_key: j
            for j in (
                await s.execute(select(Job).where(Job.dedupe_key.in_(set(keys.values())), Job.fetched_at >= now - timedelta(days=60)))
            ).scalars()
        }
        keep = []
        for i, p in enumerate(postings):
            other = existing.get(keys[i])
            if other and (other.source, other.external_id) != (p.source, p.external_id):
                links = list(other.apply_links or []) or [
                    {"publisher": other.publisher or other.source, "url": other.url, "direct": other.source in FIRST_PARTY}
                ]
                known = {a.get("url") for a in links}
                other.apply_links = links + [a for a in _links(p) if a.get("url") not in known]
                other.last_seen_at = now
                result.merged += 1
            else:
                keep.append(i)
    postings = [postings[i] for i in keep]
    keys = {n: keys[i] for n, i in enumerate(keep)}
    if not postings:
        return result

    # Apply-link check, once per job (not per user): only aggregator postings we haven't stored yet.
    status: dict[int, str] = {}
    if settings.verify_links:
        async with session_scope() as s:
            already = set(
                (
                    await s.execute(
                        select(Job.source, Job.external_id).where(tuple_(Job.source, Job.external_id).in_([(p.source, p.external_id) for p in postings]))
                    )
                ).all()
            )
        fresh = [p for p in postings if (p.source, p.external_id) not in already]
        async with egress.client("sources", headers={"User-Agent": USER_AGENT}) as client:
            checked = await verify_postings(client, fresh)
        index = {id(p): i for i, p in enumerate(postings)}
        status = {index[id(fresh[i])]: st for i, st in checked.items()}
    result.dead = sum(1 for st in status.values() if st == "dead")
    alive = [(i, p) for i, p in enumerate(postings) if status.get(i) != "dead"]
    if not alive:
        return result
    async with session_scope() as s:
        reposts = dict(
            (
                await s.execute(
                    select(Job.dedupe_key, func.count())
                    .where(Job.dedupe_key.in_({keys[i] for i, _ in alive}), Job.fetched_at >= now - timedelta(days=90))
                    .group_by(Job.dedupe_key)
                )
            ).all()
        )
    ghosts = {
        i: ghost_assessment(p, "ok" if p.source in FIRST_PARTY else status.get(i, "unverified"), reposts.get(keys[i], 0), now) for i, p in alive
    }

    rows = [
        {
            "id": uuid.uuid4(),
            "source": p.source,
            "external_id": p.external_id,
            "company": p.company[:200],
            "title": p.title[:300],
            "location": (p.location or "")[:200],
            "remote": p.remote,
            "url": (p.url or "")[:1000],
            "description": p.description[:20000],
            "salary_min": p.salary_min,
            "salary_max": p.salary_max,
            "recruiter_email": p.recruiter_email,
            "skills": extract_skills(f"{p.title}\n{p.description}"),
            "track": classify_track(p.title),
            "posted_at": p.posted_at,
            "publisher": p.publisher or COMPANY_SITE.get(p.source),
            "apply_links": _links(p),
            "company_domain": p.company_domain,
            "link_status": "ok" if p.source in FIRST_PARTY else status.get(i, "unverified"),
            "verified_at": now,
            "dedupe_key": keys[i],
            "entry_level": bool(p.extra.get("entry_level")),
            "ghost_risk": ghosts[i][0],
            "ghost_reasons": ghosts[i][1],
            "repost_count": reposts.get(keys[i], 0),
        }
        for i, p in alive
    ]
    async with session_scope() as s:
        stmt = insert(Job).values(rows)
        # Still listed -> still open: refresh the posting and its last_seen_at (stale jobs are hidden).
        stmt = stmt.on_conflict_do_update(
            constraint="uq_jobs_source_external",
            set_={
                "title": stmt.excluded.title,
                "location": stmt.excluded.location,
                "description": stmt.excluded.description,
                "url": stmt.excluded.url,
                "skills": stmt.excluded.skills,
                "track": stmt.excluded.track,
                "publisher": func.coalesce(stmt.excluded.publisher, Job.publisher),
                "apply_links": stmt.excluded.apply_links,
                "company_domain": func.coalesce(Job.company_domain, stmt.excluded.company_domain),
                "dedupe_key": stmt.excluded.dedupe_key,
                "recruiter_email": func.coalesce(stmt.excluded.recruiter_email, Job.recruiter_email),
                "entry_level": stmt.excluded.entry_level,
                "ghost_risk": stmt.excluded.ghost_risk,
                "ghost_reasons": stmt.excluded.ghost_reasons,
                "repost_count": func.greatest(Job.repost_count, stmt.excluded.repost_count),
                "last_seen_at": func.now(),
            },
        )
        # xmax = 0 only for rows this statement inserted (an update leaves the old row's xid there).
        returned = (await s.execute(stmt.returning(Job.id, literal_column("(xmax = 0)").label("inserted")))).all()
        result.job_ids = [r.id for r in returned]
        result.inserted_ids = [r.id for r in returned if r.inserted]
        to_embed = (await s.execute(select(Job).where(Job.id.in_(result.job_ids), Job.embedding.is_(None)))).scalars().all()
        if to_embed:
            vectors = await get_embedder().embed([job_embedding_text(j.title, j.company, j.description) for j in to_embed])
            for j, v in zip(to_embed, vectors):
                j.embedding = v
        # Verifier v2 rules on every new posting, so each one carries a verification from the start. The agent
        # re-checks (with the AI second opinion) when a posting reaches someone's run.
        from app.agents.verifier import apply_verdict

        for j in (await s.execute(select(Job).where(Job.id.in_(result.inserted_ids)))).scalars().all():
            await apply_verdict(s, j, now)
    return result


def job_as_posting(j: Job) -> Posting:
    """A stored job in the shape the relevance filters take."""
    return Posting(
        source=j.source,
        external_id=j.external_id,
        company=j.company,
        title=j.title,
        location=j.location or "",
        remote=j.remote,
        url=j.url,
        description=j.description or "",
        posted_at=j.posted_at,
        extra={"entry_level": j.entry_level},
    )

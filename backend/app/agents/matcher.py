"""Matcher: scores each new job against the resume.

score = blend of
  * semantic  - pgvector cosine similarity between resume and posting embeddings
  * skills    - share of the posting's skills (from the shared lexicon) the resume covers
  * llm       - a cheap-model review of the top-K candidates by similarity, with strengths and gaps
Without an LLM the first two still produce a ranked, explained list.
"""

import asyncio
import re
import uuid

from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert

from app.agents.common import PipelineState, agent_step, bump_stats, ctx_of, load_profile
from app.config import settings
from app.db import session_scope
from app.embeddings import get_embedder
from app.services.usage import usage_for
from app.llm import CallContext, LLMOutputError, LLMUnavailable, get_llm
from app.models import Job, JobMatch, Notification, Profile, Stage
from app.schemas import ResumeData
from app.skills import role_digest, skill_overlap
from app.services.events import publish

W_SEMANTIC, W_SKILLS, W_LLM = 0.25, 0.25, 0.50
W_SEMANTIC_OFFLINE, W_SKILLS_OFFLINE = 0.55, 0.45


class FitReview(BaseModel):
    fit_score: int = Field(description="0-100 overall fit for this candidate")
    strengths: list[str] = Field(description="Requirements the resume clearly demonstrates (max 6, short)")
    gaps: list[str] = Field(description="Important requirements missing from the resume (max 6, short)")
    explanation: str = Field(description="One or two plain sentences on why")


REVIEW_SYSTEM = """You are a meticulous technical recruiter screening internship candidates.
Judge fit using only what the resume actually shows. A requirement counts as a strength only if the
resume demonstrates it; list required-but-missing items as gaps. Treat 'nice to have' items as minor.
Calibrate: 80+ = would shortlist immediately, 60-79 = plausible, 40-59 = stretch, <40 = poor fit.
Seniority mismatch (e.g. 5+ years required) caps the score at 30."""


def blend(semantic: float, skills: float, llm_score: float | None) -> float:
    if llm_score is None:
        return W_SEMANTIC_OFFLINE * semantic + W_SKILLS_OFFLINE * skills
    return W_SEMANTIC * semantic + W_SKILLS * skills + W_LLM * max(0.0, min(100.0, llm_score))


_SENIOR = re.compile(r"\b(senior|sr\.?|lead|staff|principal|manager|head of|director)\b", re.IGNORECASE)
_YEARS = re.compile(r"\b([3-9]|1\d)\+?\s*(?:years|yrs)\b", re.IGNORECASE)


def level_factor(title: str, description: str) -> float:
    """Internship hunting: a senior title or a multi-year requirement makes a posting a poor fit
    no matter how well the skills line up."""
    if _SENIOR.search(title):
        return 0.5
    if _YEARS.search(description[:4000]):
        return 0.7
    return 1.0


def explain(strengths: list[str], gaps: list[str]) -> str:
    parts = []
    if strengths:
        parts.append("Strong: " + ", ".join(strengths[:5]) + ".")
    if gaps:
        parts.append("Missing: " + ", ".join(gaps[:4]) + ".")
    return " ".join(parts) or "Little overlap with the listed requirements."


def resume_for_prompt(resume: ResumeData) -> str:
    return resume.model_dump_json(exclude={"phone", "email", "links"}, exclude_defaults=True)[:12000]


async def review_fit(job: Job, resume_json: str, ctx: CallContext) -> FitReview | None:
    try:
        return await get_llm().structured(
            agent="matcher",
            tier="fast",
            system=REVIEW_SYSTEM,
            prompt=(
                f"<resume>\n{resume_json}\n</resume>\n\n"
                f"<job title=\"{job.title}\" company=\"{job.company}\" location=\"{job.location}\">\n"
                f"{role_digest(job.description, 3500)}\n</job>"
            ),
            schema=FitReview,
            ctx=ctx,
            max_tokens=4000,
        )
    except (LLMUnavailable, LLMOutputError):
        return None


async def ensure_profile_embedding(profile_id: uuid.UUID, resume: ResumeData) -> list[float]:
    vec = await get_embedder().embed_one(resume.embedding_text())
    async with session_scope() as s:
        await s.execute(update(Profile).where(Profile.id == profile_id).values(embedding=vec))
    return vec


async def run_matcher(state: PipelineState) -> dict:
    async with agent_step(state, "matcher") as step:
        profile, resume, prefs = await load_profile(state["user_id"])
        profile_vec = (
            list(profile.embedding) if profile.embedding is not None else await ensure_profile_embedding(profile.id, resume)
        )
        # Rescore mode: after you answer skill questions, re-check the jobs those answers could unlock.
        rescore = [uuid.UUID(m) for m in state.get("rescore_match_ids", [])]
        if rescore:
            async with session_scope() as s:
                job_ids = list(
                    (
                        await s.execute(
                            select(JobMatch.job_id).where(
                                JobMatch.id.in_(rescore), JobMatch.user_id == uuid.UUID(state["user_id"]), JobMatch.stage == Stage.found
                            )
                        )
                    ).scalars()
                )
        else:
            job_ids = [uuid.UUID(j) for j in state.get("new_job_ids", [])]
        embedder = get_embedder()

        async with session_scope() as s:
            distance = Job.embedding.cosine_distance(profile_vec)
            rows = (
                await s.execute(select(Job, distance.label("dist")).where(Job.id.in_(job_ids)).order_by(distance))
            ).all()

        scored = []
        for job, dist in rows:
            semantic = embedder.to_score(1.0 - float(dist if dist is not None else 1.0))
            strengths, gaps, skills = skill_overlap(resume.skills, job.skills or [])
            scored.append({"job": job, "semantic": semantic, "skills": skills, "strengths": strengths, "gaps": gaps})
        scored.sort(key=lambda r: blend(r["semantic"], r["skills"], None), reverse=True)

        resume_json = resume_for_prompt(resume)
        top = scored[: settings.llm_score_top_k]
        reviews = await asyncio.gather(*(review_fit(r["job"], resume_json, ctx_of(state)) for r in top))
        reviewed = 0
        for r, review in zip(top, reviews):
            r["review"] = review
            reviewed += review is not None

        values = []
        for r in scored:
            review: FitReview | None = r.get("review")
            if review:
                score = blend(r["semantic"], r["skills"], review.fit_score) * level_factor(r["job"].title, r["job"].description)
                strengths = list(dict.fromkeys([*r["strengths"], *review.strengths]))[:8]
                gaps = list(dict.fromkeys([*r["gaps"], *review.gaps]))[:8]
                explanation = f"{explain(r['strengths'], r['gaps'])} {review.explanation}".strip()
            else:
                score = blend(r["semantic"], r["skills"], None) * level_factor(r["job"].title, r["job"].description)
                strengths, gaps = r["strengths"], r["gaps"]
                explanation = explain(strengths, gaps)
            values.append(
                {
                    "id": uuid.uuid4(),
                    "user_id": uuid.UUID(state["user_id"]),
                    "job_id": r["job"].id,
                    "run_id": uuid.UUID(state["run_id"]),
                    "score": round(score, 1),
                    "semantic_score": round(r["semantic"], 1),
                    "skill_score": round(r["skills"], 1),
                    "llm_score": float(review.fit_score) if review else None,
                    "strengths": strengths,
                    "gaps": gaps,
                    "explanation": explanation,
                    "stage": Stage.found,
                    # Resume layout A/B, fixed per job so the Insights page can compare which converts.
                    "resume_variant": "A" if r["job"].id.int % 2 == 0 else "B",
                }
            )

        match_ids: list[str] = []
        shortlist: list[str] = []
        if values:
            async with session_scope() as s:
                stmt = insert(JobMatch).values(values)
                if rescore:
                    rescored_fields = ("score", "semantic_score", "skill_score", "llm_score", "strengths", "gaps", "explanation", "run_id")
                    stmt = stmt.on_conflict_do_update(
                        constraint="uq_match_user_job", set_={f: getattr(stmt.excluded, f) for f in rescored_fields}
                    )
                else:
                    stmt = stmt.on_conflict_do_nothing(constraint="uq_match_user_job")
                result = await s.execute(stmt.returning(JobMatch.id, JobMatch.score, JobMatch.stage, JobMatch.job_id))
                inserted = sorted(result.all(), key=lambda x: x.score, reverse=True)
                match_ids = [str(m.id) for m in inserted]
                # Quality gate: tailored resume + draft only for the best fits, within today's plan limit and the
                # weekly cap, and never for likely ghost jobs.
                usage = await usage_for(uuid.UUID(state["user_id"]))
                cap = min(settings.tailor_top_n, usage["drafts_left"], usage["week_left"])
                ghost = {r["job"].id for r in scored if r["job"].ghost_risk == "high"}
                shortlist = [str(m.id) for m in inserted if m.score >= prefs.min_score and m.stage == Stage.found and m.job_id not in ghost][:cap]
                if shortlist:
                    await s.execute(
                        update(JobMatch).where(JobMatch.id.in_([uuid.UUID(x) for x in shortlist])).values(stage=Stage.shortlisted)
                    )
                # Tell the user about every job that now fits, not just the top few that get tailored.
                by_job = {v["job_id"]: v for v in values}
                jobs = {r["job"].id: r["job"] for r in scored}
                fits = []
                for m in inserted:
                    if m.score < prefs.min_score:
                        continue
                    v, job = by_job[m.job_id], jobs[m.job_id]
                    fits.append({"match_id": str(m.id), "title": job.title, "company": job.company, "score": round(m.score)})
                    s.add(
                        Notification(
                            user_id=uuid.UUID(state["user_id"]),
                            kind="new_match",
                            match_id=m.id,
                            title=f"{'Now a fit' if rescore else 'New match'}: {job.title} at {job.company}",
                            body=f"{round(m.score)} fit · {'Remote' if job.remote else job.location or 'India'} · {v['explanation'][:160]}",
                        )
                    )
                # Pushed to the open dashboard the moment these rows commit (before tailoring starts).
                if inserted:
                    await publish(s, state["user_id"], "new_matches", count=len(inserted), fits=fits[:5])

        strong = sum(1 for v in values if v["score"] >= prefs.min_score)
        step.detail = f"{'Re-scored' if rescore else 'Scored'} {len(values)} jobs ({reviewed} reviewed by LLM) · {strong} at or above {prefs.min_score} · shortlisted {len(shortlist)}"
        await bump_stats(state["run_id"], matched=len(values), strong_matches=strong, shortlisted=len(shortlist))
        return {"match_ids": match_ids, "shortlist_ids": shortlist, "done": ["matcher"]}

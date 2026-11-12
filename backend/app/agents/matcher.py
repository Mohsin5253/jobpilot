"""Matcher: scores each new job against the resume.

score = blend of
  * semantic  - pgvector cosine similarity between resume and posting embeddings
  * skills    - share of the posting's skills (from the shared lexicon) the resume covers
  * llm       - a cheap-model review of the top-K candidates by similarity, with strengths and gaps
Without an LLM the first two still produce a ranked, explained list.
"""

import asyncio
import re
from typing import Literal
import uuid

from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert

from app.agents.common import PipelineState, agent_step, bump_stats, ctx_of, load_profile
from app.config import settings
from app.db import session_scope
from app.safety import untrusted
from app.embeddings import get_embedder
from app.services.usage import usage_for
from app.llm import CallContext, LLMOutputError, LLMUnavailable, get_llm
from app.models import Job, JobMatch, Notification, Profile, Stage
from app.schemas import ResumeData
from app.skills import adjacent, role_digest, skill_overlap
from app.services.events import publish

W_SEMANTIC, W_SKILLS, W_LLM = 0.25, 0.25, 0.50
W_SEMANTIC_OFFLINE, W_SKILLS_OFFLINE = 0.55, 0.45


class Requirement(BaseModel):
    text: str = Field(description="One requirement from the job, short (e.g. 'Python', 'REST API design', 'SQL joins')")
    kind: Literal["must", "nice"] = Field(description="must = required / core to the role; nice = preferred, bonus, plus")
    status: Literal["met", "partial", "missing"] = Field(description="met = resume shows it in work; partial = listed or adjacent; missing")
    evidence: str = Field(default="", description="For met/partial: a short exact quote from the resume that shows it; empty if missing")


class FitReview(BaseModel):
    requirements: list[Requirement] = Field(default_factory=list, description="The job's 4-10 real requirements, must-haves first")
    fit_score: int = Field(description="0-100 overall fit for this candidate")
    strengths: list[str] = Field(description="Requirements the resume clearly demonstrates (max 6, short)")
    gaps: list[str] = Field(description="Important requirements missing from the resume (max 6, short)")
    explanation: str = Field(description="One or two plain sentences on why")


REVIEW_SYSTEM = """You screen candidates the way recruiters at large tech companies do: requirement by requirement,
with evidence. Steps:
1. List the job's real requirements (4-10), ignoring boilerplate. Mark each must (required, core to the work) or
   nice (preferred, plus, bonus).
2. For each, decide from the resume ONLY: met (shown in a project, role or bullet), partial (only listed as a skill,
   or an adjacent tool), missing. Quote the resume's own words as evidence for met/partial. Never infer skills the
   resume doesn't show.
3. fit_score: 80+ = would shortlist immediately (all musts met), 60-79 = plausible (most musts met),
   40-59 = stretch, <40 = poor fit. A seniority mismatch (e.g. 3+ years required for an intern/fresher) caps it at 30.
Strengths are met requirements; gaps are missing must-haves first."""

_WEIGHT = {"must": 3.0, "nice": 1.0}
_CREDIT = {"met": 1.0, "partial": 0.5, "missing": 0.0}


def _quoted(evidence: str, resume_text: str) -> bool:
    """The evidence really comes from the resume: most of its words appear there."""
    words = [w for w in re.findall(r"[a-z0-9+#.]{3,}", evidence.lower())]
    return bool(words) and sum(1 for w in words if w in resume_text) / len(words) >= 0.7


def audit_review(review: FitReview, resume_json: str) -> FitReview:
    """Checks every claimed match against the resume (a 'met' without a real quote is downgraded), then blends the
    holistic score with weighted requirement coverage, so one optimistic guess can't carry the score."""
    if not review.requirements:
        return review
    text = resume_json.lower()
    for r in review.requirements:
        if r.status != "missing" and not _quoted(r.evidence, text):
            r.status = "partial" if r.status == "met" and r.text.lower() in text else "missing"
    total = sum(_WEIGHT[r.kind] for r in review.requirements)
    coverage = sum(_WEIGHT[r.kind] * _CREDIT[r.status] for r in review.requirements) / total if total else 0
    musts = [r for r in review.requirements if r.kind == "must"]
    missing_musts = [r.text for r in musts if r.status == "missing"]
    score = 0.5 * review.fit_score + 0.5 * coverage * 100
    if musts and len(missing_musts) > len(musts) / 2:
        score = min(score, 55)  # most must-haves missing: a stretch at best
    review.fit_score = round(max(0, min(100, score)))
    review.strengths = list(dict.fromkeys([r.text for r in review.requirements if r.status == "met"] + review.strengths))[:6]
    review.gaps = list(dict.fromkeys(missing_musts + [r.text for r in review.requirements if r.status == "missing"] + review.gaps))[:6]
    return review


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


def explain(strengths: list[str], gaps: list[str], near: list[tuple[str, str]] | None = None) -> str:
    parts = []
    if strengths:
        parts.append("Strong: " + ", ".join(strengths[:5]) + ".")
    if near:
        parts.append("Close: " + ", ".join(f"{have} for {want}" for want, have in near[:3]) + ".")
    near_wanted = {w for w, _ in near or []}
    gaps = [g for g in gaps if g not in near_wanted]
    if gaps:
        parts.append("Missing: " + ", ".join(gaps[:4]) + ".")
    return " ".join(parts) or "Little overlap with the listed requirements."


def resume_for_prompt(resume: ResumeData) -> str:
    return resume.model_dump_json(exclude={"phone", "email", "links"}, exclude_defaults=True)[:12000]


async def review_fit(job: Job, resume_json: str, ctx: CallContext) -> FitReview | None:
    try:
        review = await get_llm().structured(
            agent="matcher",
            tier="fast",
            system=REVIEW_SYSTEM,
            prompt=(
                f"<resume>\n{resume_json}\n</resume>\n\n"
                f"<job title=\"{job.title}\" company=\"{job.company}\" location=\"{job.location}\">\n"
                f"{untrusted.wrap(role_digest(job.description, 3500), 'job_post')}\n</job>"
            ),
            schema=FitReview,
            ctx=ctx,
            max_tokens=4000,
            cache=True,  # same resume + same posting + same prompt and model -> the same fit score
        )
        return audit_review(review, resume_json)
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
        # Nothing new this run: re-rank your open matches against your current resume (it may have changed since
        # they were scored), without new-match alerts for jobs you already know about.
        recheck = not rescore and not state.get("new_job_ids") and bool(state.get("recheck_match_ids"))
        previous: dict = {}
        if recheck:
            rescore = [uuid.UUID(m) for m in state["recheck_match_ids"]]
            async with session_scope() as s:
                previous = {r.job_id: (r.score, r.stage) for r in (await s.execute(select(JobMatch).where(JobMatch.id.in_(rescore)))).scalars()}
        if rescore:
            async with session_scope() as s:
                job_ids = list(
                    (
                        await s.execute(
                            select(JobMatch.job_id).where(
                                JobMatch.id.in_(rescore),
                                JobMatch.user_id == uuid.UUID(state["user_id"]),
                                JobMatch.stage.in_([Stage.found, Stage.shortlisted] if recheck else [Stage.found]),
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
                await s.execute(select(Job, distance.label("dist")).where(Job.id.in_(job_ids), Job.legit_status.is_distinct_from("suspicious")).order_by(distance))
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
                explanation = f"{explain(r['strengths'], r['gaps'], adjacent(resume.skills, r['job'].skills or []))} {review.explanation}".strip()
            else:
                score = blend(r["semantic"], r["skills"], None) * level_factor(r["job"].title, r["job"].description)
                strengths, gaps = r["strengths"], r["gaps"]
                explanation = explain(strengths, gaps, adjacent(resume.skills, r["job"].skills or []))
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
                if recheck:
                    # Shortlisted jobs still missing a tailored resume (e.g. the daily limit ran out last time) get one now.
                    from app.models import TailoredResume

                    tailored = set((await s.execute(select(TailoredResume.match_id).where(TailoredResume.match_id.in_([m.id for m in inserted])))).scalars())
                    shortlist = [str(m.id) for m in inserted if m.score >= prefs.min_score and m.stage in (Stage.found, Stage.shortlisted) and m.id not in tailored and m.job_id not in ghost][:cap]
                else:
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
                    if recheck and m.job_id in previous and previous[m.job_id][0] >= prefs.min_score:
                        continue  # already a fit you were told about
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
                if inserted and (fits or not recheck):
                    await publish(s, state["user_id"], "new_matches", count=len(fits) if recheck else len(inserted), fits=fits[:5])

        strong = sum(1 for v in values if v["score"] >= prefs.min_score)
        if recheck:
            moved = sum(1 for v in values if v["job_id"] in previous and abs(v["score"] - previous[v["job_id"]][0]) >= 3)
            step.detail = f"Re-ranked your {len(values)} open matches with your current resume ({reviewed} reviewed by LLM) · {moved} moved 3+ points · {strong} at or above {prefs.min_score} · {len(shortlist)} to tailor"
            await bump_stats(state["run_id"], matched=len(values), strong_matches=strong, shortlisted=len(shortlist))
            return {"match_ids": match_ids, "shortlist_ids": shortlist, "done": ["matcher"]}
        step.detail = f"{'Re-scored' if rescore else 'Scored'} {len(values)} jobs ({reviewed} reviewed by LLM) · {strong} at or above {prefs.min_score} · shortlisted {len(shortlist)}"
        await bump_stats(state["run_id"], matched=len(values), strong_matches=strong, shortlisted=len(shortlist))
        return {"match_ids": match_ids, "shortlist_ids": shortlist, "done": ["matcher"]}

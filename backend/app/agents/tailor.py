"""Tailor: rephrases the most relevant resume bullets for each shortlisted job.

Hard rule: only rephrase what the resume already says. Every rewrite cites its source bullet id and
is checked by the guard; a rewrite that adds a tool, a claim or a number is reverted to the original.
"""

import asyncio
import uuid

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.agents.common import safe_job, PipelineState, agent_step, bump_stats, ctx_of, load_profile
from app.agents.guard import bullet_contexts, check_claim, proof_contexts, resume_skillset, source_label
from app.logging import log
from app.services.evidence import evidenced_skills
from app.db import session_scope
from app.safety import untrusted
from app.llm import CallContext, LLMOutputError, LLMUnavailable, get_llm
from app.models import Job, JobMatch, TailoredResume
from app.schemas import ResumeData
from app.skills import extract_skills, role_digest

MAX_BULLETS = 6


class Rewrite(BaseModel):
    source_id: str = Field(description="id of the resume bullet being rephrased, e.g. exp0.b1")
    source_refs: list[str] = Field(default_factory=list, description="every source the rewrite draws on: the bullet id, plus any proof ids (proof.gh.<repo>, proof.item.<id>) it uses")
    rewritten: str = Field(description="the rephrased bullet, at most ~30 words")
    keywords: list[str] = Field(description="job keywords this bullet now foregrounds (must already be in the source)")


class TailorOutput(BaseModel):
    bullets: list[Rewrite]


SYSTEM = """You tailor resume bullets to a specific job without ever inventing anything.

Rules (strict):
1. Choose the 4-6 bullets most relevant to the job and rephrase each one.
2. Each rewrite may only use facts from its own source bullet and that bullet's role/project header.
3. Never add a tool, language, library, metric, number, team size, outcome or responsibility that is
   not in the source. Keep every number exactly as written. If the source has no metric, add none.
4. You may reorder clauses, use the job's vocabulary for things the bullet already shows, start with
   a strong verb, and cut filler.
5. Keep each bullet to one line (about 30 words max).
6. List in source_refs every source the rewrite uses: its bullet id, and a proof id only if the rewrite names
   something that proof item shows (e.g. the repo's language). Anything without a source will be reverted."""


def _ref(sid: str, resume: ResumeData, proofs: dict[str, str]) -> dict:
    return {"id": sid, "kind": "proof" if sid.startswith("proof.") else "resume", "label": source_label(sid, resume, proofs)}


def _offline_tailor(resume: ResumeData, job_skills: list[str]) -> list[dict]:
    """No LLM: pick the bullets that overlap most with the job and keep their wording."""
    want = {s.lower() for s in job_skills}
    ranked = sorted(
        resume.bullet_index(),
        key=lambda kv: len({s.lower() for s in extract_skills(kv[1])} & want),
        reverse=True,
    )
    return [
        {
            "source_id": sid,
            "original": text,
            "rewritten": text,
            "keywords": [s for s in extract_skills(text) if s.lower() in want],
            "reverted": False,
            "source_refs": [_ref(sid, resume, {})],
            "revert_reason": "",
        }
        for sid, text in ranked[:MAX_BULLETS]
    ]


async def tailor_one(match: JobMatch, resume: ResumeData, resume_text: str, ctx: CallContext, evidence: dict | None = None) -> tuple[list[dict], dict, str]:
    index = dict(resume.bullet_index())
    proofs = proof_contexts(evidence)
    if not index:
        return [], {"passed": True, "checked": 0, "violations": [], "note": "resume has no bullets"}, "none"

    job = match.job
    try:
        out = await get_llm().structured(
            agent="tailor",
            tier="smart",
            system=SYSTEM,
            prompt=(
                "<resume_bullets>\n"
                + "\n".join(f"[{sid}] {text}" for sid, text in index.items())
                + "\n</resume_bullets>\n\n"
                + "<headers>\n"
                + "\n".join(f"exp{i}: {e.title} at {e.organization}" for i, e in enumerate(resume.experience))
                + "\n"
                + "\n".join(f"proj{i}: {p.name} ({', '.join(p.tech)})" for i, p in enumerate(resume.projects))
                + "\n"
                + "\n".join(f"add{i}: {a.skill} (described by the candidate)" for i, a in enumerate(resume.additional))
                + "\n</headers>\n\n"
                + ("<proof>\n" + "\n".join(f"[{pid}] {text}" for pid, text in proofs.items()) + "\n</proof>\n\n" if proofs else "")
                + f"<job title=\"{job.title}\" company=\"{job.company}\">\n{untrusted.wrap(role_digest(job.description, 4000), 'job_post')}\n</job>\n\n"
                + f"Candidate strengths for this job: {', '.join(match.strengths) or 'n/a'}"
            ),
            schema=TailorOutput,
            ctx=ctx,
        )
        model = get_llm().model_for("smart")
        rewrites = out.bullets[:MAX_BULLETS]
    except (LLMUnavailable, LLMOutputError):
        return _offline_tailor(resume, job.skills or []), {"passed": True, "checked": 0, "violations": [], "note": "offline: original bullets ranked by relevance"}, "offline"

    contexts = {**bullet_contexts(resume), **proofs}
    allowed = resume_skillset(resume, resume_text) | set(evidenced_skills(evidence or {}))
    bullets, violations = [], []
    for rw in rewrites:
        refs = list(dict.fromkeys([*rw.source_refs, rw.source_id]))
        verdict = check_claim(rw.rewritten, refs, contexts, allowed)
        if not verdict.ok:
            violations.append({"source_id": rw.source_id, "rewritten": rw.rewritten, **verdict.as_dict()})
        if rw.source_id not in index:
            continue  # nothing of the resume to fall back to: the bullet is dropped (logged above)
        valid = verdict.sources or [rw.source_id]
        bullets.append(
            {
                "source_id": rw.source_id,
                "original": index[rw.source_id],
                "rewritten": rw.rewritten if verdict.ok else index[rw.source_id],
                "keywords": [k for k in rw.keywords if k.lower() in contexts[rw.source_id].lower()],
                "reverted": not verdict.ok,
                # Reverted lines go back to the original resume line, so their source is that line alone.
                "source_refs": [_ref(r, resume, proofs) for r in (valid if verdict.ok else [rw.source_id])],
                "revert_reason": verdict.reason,
            }
        )
    if violations:
        log.info("guard.reverted", match_id=str(match.id), count=len(violations))  # ids and counts only, no text
    report = {"passed": not violations, "checked": len(rewrites), "violations": violations}
    return bullets, report, model


class TargetedSummary(BaseModel):
    summary: str = Field(description="2-3 sentences, 30-60 words, aimed at this role")


SUMMARY_SYSTEM = """Write the summary at the top of a resume tailored to one job, for a student or fresher. 2-3 sentences, 30-60
words, no first person, no clichés. Name the role. Use ONLY facts from the resume given (degree, college, skills,
projects, experience) and lead with the ones this job asks for. Never invent tools, numbers, results or experience."""


async def targeted_summary(match: JobMatch, resume: ResumeData, resume_text: str, ctx: CallContext) -> str:
    """A summary aimed at this job, from the resume's own facts. Checked like any rewrite: a summary naming a tool
    the resume doesn't show is replaced by the rule-based one."""
    from app.services.ats import detect_industry
    from app.services.resume_improve import template_summary

    job = match.job
    wanted = {s.lower() for s in [*(job.skills or []), *match.strengths]}
    top = sorted(resume.skills, key=lambda s: 0 if s.lower() in wanted else 1)[:6]
    fallback = template_summary(resume, detect_industry(job.title, job.description or "")[0], top).replace("Seeking", f"Applying for the {job.title} role; seeking", 1)
    if not (resume.skills or resume.experience or resume.projects):
        return resume.summary or ""
    try:
        out = await get_llm().structured(
            agent="tailor",
            tier="fast",
            system=SUMMARY_SYSTEM,
            prompt=(
                f"Job: {job.title} at {job.company}\nWhat it asks for: {', '.join((job.skills or [])[:10]) or role_digest(job.description, 600)}\n"
                f"Education: {'; '.join(f'{e.degree} {e.school}'.strip() for e in resume.education) or 'n/a'}\nSkills: {', '.join(resume.skills)}\n"
                f"Experience: {'; '.join(f'{e.title} at {e.organization}' for e in resume.experience) or 'none'}\nProjects: {'; '.join(p.name for p in resume.projects) or 'none'}\n"
                f"Current summary: {resume.summary or '(none)'}"
            ),
            schema=TargetedSummary,
            ctx=ctx,
            max_tokens=400,
        )
        text = out.summary.strip()
        allowed = resume_skillset(resume, resume_text)
        from app.agents.guard import check_freeform

        if text and "[" not in text and 15 <= len(text.split()) <= 90 and not check_freeform(text, allowed):
            return text
    except (LLMUnavailable, LLMOutputError):
        pass
    return fallback


async def run_tailor(state: PipelineState) -> dict:
    async with agent_step(state, "tailor") as step:
        profile, resume, _ = await load_profile(state["user_id"])
        ids = [uuid.UUID(x) for x in state.get("shortlist_ids", [])]
        async with session_scope() as s:
            # Never tailor for a blocked posting, or one whose text tries to steer AI tools (prompt injection).
            matches = (await s.execute(select(JobMatch).join(Job, Job.id == JobMatch.job_id).where(JobMatch.id.in_(ids), *safe_job()))).scalars().all()

        results = await asyncio.gather(*(tailor_one(m, resume, profile.resume_text, ctx_of(state), profile.evidence) for m in matches))
        summaries = await asyncio.gather(*(targeted_summary(m, resume, profile.resume_text, ctx_of(state)) for m in matches))
        rows, reverted = [], 0
        has_resume = bool(resume.skills or resume.summary or resume.experience or resume.projects)
        for m, (bullets, report, model), summary in zip(matches, results, summaries):
            if not bullets and not has_resume:
                continue
            # A resume without bullet points still gets a tailored version (job's skills first, sections in the
            # job's order), so Outreach drafts the application instead of the run ending with nothing.
            reverted += sum(b["reverted"] for b in bullets)
            # The job-targeted summary rides in the guard report (it was checked by the same guard).
            rows.append({"id": uuid.uuid4(), "match_id": m.id, "bullets": bullets, "guard_report": {**report, "summary": summary}, "model": model})
        if rows:
            async with session_scope() as s:
                stmt = insert(TailoredResume).values(rows)
                await s.execute(
                    stmt.on_conflict_do_update(
                        index_elements=[TailoredResume.match_id],
                        set_={"bullets": stmt.excluded.bullets, "guard_report": stmt.excluded.guard_report, "model": stmt.excluded.model},
                    )
                )
        tailored = [str(r["match_id"]) for r in rows]
        step.detail = f"Tailored {len(tailored)} resumes · guard reverted {reverted} bullet(s)"
        await bump_stats(state["run_id"], tailored=len(tailored), guard_reverts=reverted)
        return {"tailored_ids": tailored, "done": ["tailor"]}

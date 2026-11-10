"""Tailor: rephrases the most relevant resume bullets for each shortlisted job.

Hard rule: only rephrase what the resume already says. Every rewrite cites its source bullet id and
is checked by the guard; a rewrite that adds a tool, a claim or a number is reverted to the original.
"""

import asyncio
import uuid

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.agents.common import PipelineState, agent_step, bump_stats, ctx_of, load_profile
from app.agents.guard import bullet_contexts, check_claim, proof_contexts, resume_skillset, source_label
from app.logging import log
from app.services.evidence import evidenced_skills
from app.db import session_scope
from app.llm import CallContext, LLMOutputError, LLMUnavailable, get_llm
from app.models import JobMatch, TailoredResume
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
                + f"<job title=\"{job.title}\" company=\"{job.company}\">\n{role_digest(job.description, 4000)}\n</job>\n\n"
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


async def run_tailor(state: PipelineState) -> dict:
    async with agent_step(state, "tailor") as step:
        profile, resume, _ = await load_profile(state["user_id"])
        ids = [uuid.UUID(x) for x in state.get("shortlist_ids", [])]
        async with session_scope() as s:
            matches = (await s.execute(select(JobMatch).where(JobMatch.id.in_(ids)))).scalars().all()

        results = await asyncio.gather(*(tailor_one(m, resume, profile.resume_text, ctx_of(state), profile.evidence) for m in matches))
        rows, reverted = [], 0
        for m, (bullets, report, model) in zip(matches, results):
            if not bullets:
                continue
            reverted += sum(b["reverted"] for b in bullets)
            rows.append({"id": uuid.uuid4(), "match_id": m.id, "bullets": bullets, "guard_report": report, "model": model})
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

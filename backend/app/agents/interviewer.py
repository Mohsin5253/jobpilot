"""Interviewer: turns "your resume doesn't quite fit" into questions instead of dead ends.

For near-miss jobs (scored within settings.near_miss_band below your minimum), it collects the concrete
skills you're missing, ranks them by how many jobs they'd unlock, and asks you about each one once.
Answering "yes" with a sentence about how you used it adds the skill to your profile in your own words;
the jobs it could unlock are then re-scored and, if they now fit, tailored and drafted. The Tailor may
only use what you wrote, so nothing is fabricated. Asking never blocks the rest of the run.
"""

import uuid
from collections import defaultdict

from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert

from app.agents.common import PipelineState, agent_step, bump_stats, ctx_of, load_profile
from app.config import settings
from app.db import session_scope
from app.llm import LLMOutputError, LLMUnavailable, get_llm
from app.models import JobMatch, Notification, QuestionStatus, SkillQuestion
from app.skills import SKILLS, canonicalize


class Question(BaseModel):
    skill: str
    question: str = Field(description="One friendly, specific question, under 35 words")


class Questions(BaseModel):
    questions: list[Question]


SYSTEM = """You help a student close gaps between their resume and internship postings.
For each skill, write one short, friendly question asking whether they have used it and, if so, to
describe one concrete thing they did with it (a project, coursework, a task). Mention the kind of job
it would help with. Never assume they have the skill. Plain language, no preamble."""


def template_question(skill: str, jobs: list[str]) -> str:
    where = f" ({jobs[0]})" if jobs else ""
    return f"Have you worked with {skill}? Several roles you nearly match{where} ask for it. If yes, describe one thing you did with it."


async def run_interviewer(state: PipelineState) -> dict:
    async with agent_step(state, "interviewer") as step:
        _, resume, prefs = await load_profile(state["user_id"])
        user_id = uuid.UUID(state["user_id"])
        floor = prefs.min_score - settings.near_miss_band
        ids = [uuid.UUID(m) for m in state.get("match_ids", [])]

        async with session_scope() as s:
            # Near-miss: the blended score is just under your bar, or the recruiter-style LLM review
            # rates the fit close to it even though embeddings/skill overlap pulled the blend down.
            near = (
                (
                    await s.execute(
                        select(JobMatch).where(
                            JobMatch.id.in_(ids),
                            JobMatch.score < prefs.min_score,
                            or_(JobMatch.score >= floor, JobMatch.llm_score >= prefs.min_score - 10),
                        )
                    )
                )
                .scalars()
                .all()
            )
            existing = {q.skill.lower(): q for q in (await s.execute(select(SkillQuestion).where(SkillQuestion.user_id == user_id))).scalars()}

        have = {x.lower() for x in resume.skills}
        unlocks: dict[str, list[JobMatch]] = defaultdict(list)
        for m in near:
            for raw in [*m.gaps, *(m.job.skills or [])]:
                skill = canonicalize(raw)
                if skill in SKILLS and skill.lower() not in have and m not in unlocks[skill]:
                    unlocks[skill].append(m)

        # Already asked: an open question just learns about more jobs it would unlock; answered ones stay answered.
        extended = 0
        async with session_scope() as s:
            for skill, ms in unlocks.items():
                q = existing.get(skill.lower())
                if q and q.status == QuestionStatus.open:
                    row = await s.get(SkillQuestion, q.id)
                    row.match_ids = list(dict.fromkeys([*row.match_ids, *(str(m.id) for m in ms)]))
                    extended += 1

        fresh = sorted(
            (k for k in unlocks if k.lower() not in existing),
            key=lambda k: (len(unlocks[k]), max(m.score for m in unlocks[k])),
            reverse=True,
        )[: settings.max_questions_per_run]
        if not fresh:
            step.detail = f"No new skill gaps to ask about ({len(near)} near-miss jobs{f', {extended} open question(s) updated' if extended else ''})"
            return {"question_ids": [], "done": ["interviewer"]}

        examples = {k: [f"{m.job.title} at {m.job.company}" for m in unlocks[k][:2]] for k in fresh}
        texts = {k: template_question(k, examples[k]) for k in fresh}
        try:
            out = await get_llm().structured(
                agent="interviewer",
                tier="fast",
                system=SYSTEM,
                prompt=(
                    "Write one question per skill below. Use the skill name exactly as given.\n"
                    + "\n".join(f"- {k}: needed by {', '.join(examples[k])}" for k in fresh)
                ),
                schema=Questions,
                ctx=ctx_of(state),
                max_tokens=3000,
            )
            for q in out.questions:
                skill = canonicalize(q.skill)
                if skill in texts and q.question.strip():
                    texts[skill] = q.question.strip()
        except (LLMUnavailable, LLMOutputError):
            pass

        async with session_scope() as s:
            result = await s.execute(
                insert(SkillQuestion)
                .values(
                    [
                        {
                            "id": uuid.uuid4(),
                            "user_id": user_id,
                            "run_id": uuid.UUID(state["run_id"]),
                            "skill": k,
                            "question": texts[k],
                            "match_ids": [str(m.id) for m in unlocks[k]],
                            "status": QuestionStatus.open,
                        }
                        for k in fresh
                    ]
                )
                .on_conflict_do_nothing(constraint="uq_question_user_skill")
                .returning(SkillQuestion.id)
            )
            qids = [str(x) for x in result.scalars()]
            if qids:
                s.add(
                    Notification(
                        user_id=user_id,
                        kind="skills",
                        title=f"{len(qids)} quick question{'s' if len(qids) > 1 else ''} could unlock more jobs",
                        body=f"Do you have {', '.join(fresh[:4])}? Answer in Skill check and the agents re-check those jobs.",
                    )
                )

        jobs_touched = len({m.id for k in fresh for m in unlocks[k]})
        step.detail = f"Asked you about {len(qids)} skill(s) — {', '.join(fresh)} — that could unlock {jobs_touched} near-miss job(s)"
        await bump_stats(state["run_id"], questions=len(qids))
        return {"question_ids": qids, "done": ["interviewer"]}

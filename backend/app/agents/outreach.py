"""Outreach: per tailored job, an application email + LinkedIn note to the best real contact, and a
referral request (referrals are a small share of applications but an outsized share of hires). The
referral goes to a real, publicly listed employee in the role's team when one is known; otherwise it is a
note the student sends to an alum themselves. LinkedIn is never automated. Drafts are created as
`pending`: nothing leaves the system until the user approves it."""

import asyncio
import uuid

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.agents.common import safe_job, PipelineState, agent_step, bump_stats, ctx_of, load_profile
from app.agents.guard import check_freeform, resume_skillset
from app.db import session_scope
from app.safety import untrusted
from app.llm import CallContext, LLMOutputError, LLMUnavailable, get_llm
from app.logging import log
from app.models import CompanyContact, DraftStatus, Job, JobMatch, OutreachDraft
from app.services.contacts import find_contacts, official_address
from app.schemas import ResumeData
from app.skills import role_digest


class OutreachOutput(BaseModel):
    subject: str = Field(description="Specific subject line, under 70 characters")
    email_body: str = Field(description="4-5 short lines, plain text, signed with the candidate's first name")
    linkedin_note: str = Field(description="Connection note under 300 characters")


SYSTEM = """You write short, specific cold outreach for an internship or entry-level candidate.
Email: 4-5 lines. Line 1 says who they are and which role. Lines 2-3 cite one or two concrete things
from the candidate's own experience that match the role. Final line asks for a quick chat or how to
apply. Sign off with the candidate's first name. No flattery, no buzzwords, no "I hope this finds you well".
LinkedIn note: under 300 characters, same facts, friendlier.
Only mention skills, projects and results that appear in the material provided. Never invent anything.
If a recipient is named, greet them by first name and write to them as someone senior at the company who
could point the candidate to the right team. Do not claim to know anything about them (no talks, posts,
papers or projects of theirs) beyond their name and role. Otherwise greet the company's hiring team."""


REFERRAL_SYSTEM = """You write a short, polite referral request from a student to an employee at a company.
4 lines at most. Say who the student is (degree, college) and which role they are applying for. Cite one
concrete, relevant thing from their own experience. Ask whether the person would be open to referring them,
or pointing them to the right person, and offer to share the resume. No flattery, no pressure, nothing
invented, no claims about the recipient. Sign off with the candidate's first name. Also give a LinkedIn
version under 300 characters."""


# What hiring teams in each field look for in a first email from an intern or fresher (used by the AI draft and the
# template): the proof to point to and the tone.
OUTREACH_NORMS = {
    "software": "Lead with one shipped project and its tech stack; link the GitHub repo or a live demo; mention DSA/coding profile only if strong.",
    "data_science": "Lead with one model or analysis and its metric (accuracy, F1, uplift); link the notebook, repo or Kaggle; name the libraries actually used.",
    "data_analytics": "Lead with a dashboard or analysis and the business decision it informed; name SQL/Excel/Power BI where used.",
    "product": "Lead with a product insight or teardown and a metric you'd move; show user empathy and structured thinking, briefly.",
    "design": "Lead with the portfolio link and one case study's outcome; keep it visual-first and short.",
    "marketing": "Lead with a campaign or content result in numbers (reach, CTR, followers, leads); link the work.",
    "finance": "Lead with relevant coursework or certifications (CA/CFA/NISM) and one analysis; keep it formal and precise.",
    "consulting": "Lead with a case-competition result or structured project; crisp, formal, one clear ask.",
    "sales": "Lead with a result in numbers (targets, leads, revenue); confident and brief, ask for a short call.",
    "hr": "Lead with recruiting, events or people-ops experience; warm, professional tone.",
    "core_engineering": "Lead with a lab, final-year project or internship with tools used (CAD, MATLAB, PLC); mention certifications if any.",
    "operations": "Lead with a process you improved and its measurable effect; practical tone.",
}


def _industry(job) -> str:
    from app.services.ats import detect_industry

    return detect_industry(job.title, job.description or "")[0]


def _proof_url(resume: ResumeData, industry: str) -> str:
    from app.ats_lexicon import INDUSTRIES

    hints = INDUSTRIES[industry].proof_links if industry in INDUSTRIES else ()
    return next((link for link in resume.links if any(h in link.lower() for h in hints)), "")


def _first_name(resume: ResumeData) -> str:
    return (resume.name or "").split(" ")[0] or "there"


def greeting(job, recipient: CompanyContact | None) -> str:
    if recipient and recipient.kind == "person" and recipient.first_name:
        return f"Hi {recipient.first_name},"
    return f"Hi {job.company} team,"


def template_draft(resume: ResumeData, match: JobMatch, bullets: list[dict], recipient: CompanyContact | None = None) -> OutreachOutput:
    job, name = match.job, _first_name(resume)
    edu = resume.education[0] if resume.education else None
    school = (f"{edu.degree} student at {edu.school}" if edu and edu.degree else edu.school) if edu else ""
    strengths = ", ".join(match.strengths[:3])
    proof = bullets[0]["rewritten"].rstrip(".") if bullets else ""
    lines = [
        greeting(job, recipient),
        "",
        f"I'm {resume.name or name}{f' ({school})' if school else ''}, and I'd love to be considered for the {job.title} role.",
    ]
    if strengths:
        lines.append(f"I work with {strengths}" + (f", most recently: {proof[0].lower() + proof[1:]}." if proof else "."))
    url = _proof_url(resume, _industry(job))
    if url:
        lines.append(f"You can see my work here: {url}")
    lines += [
        "I've attached my resume, tailored for this role.",
        f"I'd appreciate a quick chat about how I could contribute to {job.company}'s team.",
        "",
        "Thanks,",
        name,
    ]
    note = f"Hi! I'm {name}, interested in the {job.title} role at {job.company}. I work with {strengths or 'Python and ML'} and would love to connect."
    return OutreachOutput(subject=f"{job.title} — {resume.name or name}"[:70], email_body="\n".join(lines), linkedin_note=note[:300])


def referral_template(resume: ResumeData, match: JobMatch, bullets: list[dict], person: CompanyContact | None) -> OutreachOutput:
    job, name = match.job, _first_name(resume)
    edu = resume.education[0] if resume.education else None
    who = f"{edu.degree} student at {edu.school}" if edu and edu.degree and edu.school else "a student"
    proof = bullets[0]["rewritten"].rstrip(".") if bullets else ""
    hello = f"Hi {person.first_name}," if person and person.first_name else "Hi,"
    body = [
        hello,
        "",
        f"I'm {resume.name or name}, {who}, and I'm applying for the {job.title} role at {job.company}.",
        *([f"Most relevant to it: {proof[0].lower() + proof[1:]}."] if proof else []),
        "Would you be open to referring me, or pointing me to the right person? I'm happy to share my resume.",
        "",
        "Thank you,",
        name,
    ]
    note = f"Hi{' ' + person.first_name if person and person.first_name else ''}! I'm {name}, applying for the {job.title} role at {job.company}. Would you be open to a referral or a quick pointer? Happy to share my resume."
    return OutreachOutput(subject=f"Referral for {job.title}?"[:70], email_body="\n".join(body), linkedin_note=note[:300])


async def referral_one(match: JobMatch, resume: ResumeData, resume_text: str, ctx: CallContext, person: CompanyContact | None) -> OutreachOutput:
    bullets = (match.tailored.bullets if match.tailored else []) or []
    job = match.job
    to = f"Recipient: {person.first_name}, {person.position or 'employee'} at {job.company}\n" if person and person.first_name else f"Recipient: an alum or employee at {job.company} (name unknown)\n"
    try:
        out = await get_llm().structured(
            agent="outreach",
            tier="smart",
            system=REFERRAL_SYSTEM,
            prompt=(
                to
                + f"Candidate: {resume.name}\nEducation: {'; '.join(f'{e.degree} {e.school}'.strip() for e in resume.education) or 'n/a'}\n"
                + f"Role: {job.title} at {job.company}\nRelevant experience (factual):\n"
                + "\n".join(f"- {b['rewritten']}" for b in bullets[:3])
            ),
            schema=OutreachOutput,
            ctx=ctx,
            max_tokens=3000,
        )
    except (LLMUnavailable, LLMOutputError):
        return referral_template(resume, match, bullets, person)
    if check_freeform(f"{out.email_body}\n{out.linkedin_note}", resume_skillset(resume, resume_text)):
        return referral_template(resume, match, bullets, person)
    out.linkedin_note = out.linkedin_note[:300]
    return out


def referral_person(ranked: list[CompanyContact], recipient: CompanyContact | None) -> CompanyContact | None:
    """A real person who isn't the application's recipient and isn't an executive: a peer who can refer."""
    for c in ranked:
        if c.kind == "person" and c is not recipient and c.seniority != "executive" and c.first_name:
            return c
    return None


def with_proof(body: str, proof_url: str | None) -> str:
    return f"{body.rstrip()}\n\nProof of my work: {proof_url}" if proof_url else body


async def draft_one(match: JobMatch, resume: ResumeData, resume_text: str, ctx: CallContext, recipient: CompanyContact | None = None) -> OutreachOutput:
    bullets = (match.tailored.bullets if match.tailored else []) or []
    job = match.job
    to_line = (
        f"Recipient: {recipient.first_name} {recipient.last_name}, {recipient.position or 'senior team member'} at {job.company}\n"
        if recipient and recipient.kind == "person" and recipient.first_name
        else f"Recipient: the {job.company} hiring team\n"
    )
    industry = _industry(job)
    url = _proof_url(resume, industry)
    try:
        out = await get_llm().structured(
            agent="outreach",
            tier="smart",
            system=SYSTEM,
            prompt=(
                to_line
                + f"Field norms for this email: {OUTREACH_NORMS.get(industry, OUTREACH_NORMS['software'])}\n"
                + (f"Proof-of-work link to include: {url}\n" if url else "")
                + "Mention that the resume (tailored for this role) is attached.\n"
                + f"Candidate: {resume.name}\n"
                f"Education: {'; '.join(f'{e.degree} {e.school}'.strip() for e in resume.education) or 'n/a'}\n"
                f"Relevant experience (already tailored, factual):\n"
                + "\n".join(f"- {b['rewritten']}" for b in bullets[:5])
                + f"\nMatching strengths: {', '.join(match.strengths[:6])}\n\n"
                f"<job title=\"{job.title}\" company=\"{job.company}\" location=\"{job.location}\">\n{untrusted.wrap(role_digest(job.description, 2500), 'job_post')}\n</job>"
            ),
            schema=OutreachOutput,
            ctx=ctx,
            max_tokens=6000,
        )
    except (LLMUnavailable, LLMOutputError):
        return template_draft(resume, match, bullets, recipient)

    # Same guard as the Tailor: an email that names a tool the candidate never used is discarded.
    skills = resume_skillset(resume, resume_text)
    if check_freeform(f"{out.email_body}\n{out.linkedin_note}", skills):
        return template_draft(resume, match, bullets, recipient)
    out.linkedin_note = out.linkedin_note[:300]
    # Always open with the right greeting: the recipient's first name, or the company's hiring team.
    if not out.email_body.lstrip().lower().startswith(("hi ", "hello", "dear")):
        out.email_body = f"{greeting(job, recipient)}\n\n{out.email_body.lstrip()}"
    return out


async def proof_link(profile) -> str | None:
    from app.config import settings
    from app.services.consent import has

    if not profile.proof_slug:
        return None
    async with session_scope() as s:
        if not await has(s, profile.user_id, "public_proof"):
            return None
    return f"{settings.app_url.rstrip('/')}/p/{profile.proof_slug}"


async def run_outreach(state: PipelineState) -> dict:
    async with agent_step(state, "outreach") as step:
        profile, resume, _ = await load_profile(state["user_id"])
        ids = [uuid.UUID(x) for x in state.get("tailored_ids", [])]
        async with session_scope() as s:
            matches = (
                (await s.execute(select(JobMatch).join(Job, Job.id == JobMatch.job_id).where(JobMatch.id.in_(ids), *safe_job()).options(selectinload(JobMatch.tailored))))
                .scalars()
                .all()
            )
        async def recipient_for(m: JobMatch) -> tuple[CompanyContact | None, str | None, CompanyContact | None]:
            # A failed lookup must not block the draft: it falls back to the posting's address (or none).
            try:
                ranked = await find_contacts(m.job, ctx_of(state))
            except Exception as exc:
                log.warning("outreach.contacts_failed", company=m.job.company, error=str(exc))
                return None, None, None
            top = ranked[0] if ranked else None
            official = official_address(ranked)
            cc = official.email if top and top.kind == "person" and official else None
            return top, cc, referral_person(ranked, top)

        found = await asyncio.gather(*(recipient_for(m) for m in matches))
        recipients = [r for r, _, _ in found]
        ccs = [cc for _, cc, _ in found]
        referrers = [p for _, _, p in found]
        drafts = await asyncio.gather(*(draft_one(m, resume, profile.resume_text, ctx_of(state), r) for m, r in zip(matches, recipients)))
        referrals = await asyncio.gather(*(referral_one(m, resume, profile.resume_text, ctx_of(state), p) for m, p in zip(matches, referrers)))
        proof_url = await proof_link(profile)
        draft_ids: list[str] = []
        async with session_scope() as s:
            for m, d, r, cc, ref, p in zip(matches, drafts, recipients, ccs, referrals, referrers):
                row = OutreachDraft(
                    id=uuid.uuid4(),
                    user_id=uuid.UUID(state["user_id"]),
                    match_id=m.id,
                    run_id=uuid.UUID(state["run_id"]),
                    subject=d.subject,
                    email_body=with_proof(d.email_body, proof_url),
                    linkedin_note=d.linkedin_note,
                    to_email=r.email if r else m.job.recruiter_email,
                    contact_id=r.id if r else None,
                    cc_email=cc,
                    status=DraftStatus.pending,
                )
                s.add(row)
                draft_ids.append(str(row.id))
                ref_row = OutreachDraft(
                    id=uuid.uuid4(),
                    user_id=uuid.UUID(state["user_id"]),
                    match_id=m.id,
                    run_id=uuid.UUID(state["run_id"]),
                    kind="referral",
                    subject=ref.subject,
                    email_body=with_proof(ref.email_body, proof_url),
                    linkedin_note=ref.linkedin_note,
                    to_email=p.email if p else None,
                    contact_id=p.id if p else None,
                    status=DraftStatus.pending,
                )
                s.add(ref_row)
                draft_ids.append(str(ref_row.id))
        people = sum(1 for r in recipients if r and r.kind == "person")
        reached = sum(1 for r in recipients if r)
        named = sum(1 for p in referrers if p)
        step.detail = (
            f"Drafted {len(matches)} applications + {len(matches)} referral requests · {reached} addressed to a real contact "
            f"({people} senior people) · {named} referral(s) to a named employee · waiting for your approval"
        )
        await bump_stats(state["run_id"], drafts=len(draft_ids))
        return {"draft_ids": draft_ids, "done": ["outreach"]}

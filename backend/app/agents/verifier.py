"""Verifier: checks that every new job is a real, legitimate opening before the Matcher spends time on it.

Ingest already drops obvious scams (fees, deposits, "earn per day") and closed links. The Verifier looks at
what's left with a wider set of signals and gives each job a verdict, shown to the user with its reasons:

  verified    nothing suspicious; the apply link is live or on a company career board
  caution     something worth checking (a personal-email recruiter, a link that couldn't be opened, ...)
  suspicious  a red flag (pay-to-train, chat-only hiring, an employer with no name); never matched

Signals are rules first, so verdicts are cheap and reproducible. When the LLM is available, it gives a
second opinion on the few jobs with several caution signals, and can only make a verdict stricter.
Verdicts belong to the job (shared by every user) and are reused for a day.
"""

import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

from pydantic import BaseModel, Field
from sqlalchemy import select

from app.agents.common import PipelineState, agent_step, bump_stats, ctx_of
from app.db import session_scope
from app.llm import LLMOutputError, LLMUnavailable, get_llm
from app.models import Job

RECHECK_AFTER = timedelta(days=1)
MAX_LLM_REVIEWS = 6

ATS_HOSTS = ("greenhouse.io", "lever.co", "ashbyhq.com", "myworkdayjobs.com", "smartrecruiters.com", "workable.com", "icims.com", "taleo.net", "bamboohr.com", "recruitee.com", "teamtailor.com", "zohorecruit.com", "keka.com", "darwinbox.in")
FREE_MAIL = {"gmail.com", "yahoo.com", "yahoo.co.in", "outlook.com", "hotmail.com", "live.com", "rediffmail.com", "proton.me", "protonmail.com", "icloud.com", "aol.com", "ymail.com"}

# Every pattern is bounded by \b, so "internship fee" can't match "Internship Feeling".
_PAY_TO_WORK = re.compile(
    r"\b(training (fee|charges?)|pay (for|towards) (the )?(training|course|certificat\w*|kit|laptop)|certificat\w* fee|"
    r"(starter|joining) kit|buy (a|our) (course|kit|package)|internship fee|placement fee|"
    r"refundable after|amount (will be )?refunded)\b",
    re.IGNORECASE,
)
_CHAT_ONLY = re.compile(r"\b((contact|message|ping|dm|reach)( us| me)? (on|via) (whats\s?app|telegram|instagram)\b|whats\s?app\s*(no\b|number\b|:)|telegram\s*@)", re.IGNORECASE)
_PHONE = re.compile(r"(?<!\d)(?:\+?91[\s-]?)?[6-9]\d{9}(?!\d)")
_HYPE = re.compile(r"\b(urgent(ly)? hiring|limited (seats|slots)|100% (placement|job guarantee)|hurry|apply (now|today) (before|or)|earn (from|at) home|no experience (required|needed).{0,40}earn)\b", re.IGNORECASE)
_VAGUE_EMPLOYER = re.compile(r"^(hiring|confidential|an? (mnc|leading|reputed|top)|(leading|reputed|top) (company|mnc|firm)|client of|our client|mnc|startup)\b", re.IGNORECASE)


@dataclass
class Verdict:
    status: str = "verified"
    reasons: list[str] = field(default_factory=list)  # why it isn't verified (empty when verified)
    good: list[str] = field(default_factory=list)  # what checked out, shown on a verified job


def _host(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower().removeprefix("www.")
    except ValueError:
        return ""


def assess(job: Job) -> Verdict:
    """The rule-based verdict for one job: red flags make it suspicious, other signals ask for caution."""
    v = Verdict()
    red: list[str] = []
    caution: list[str] = []
    text = f"{job.title}\n{job.description or ''}"

    if not (job.company or "").strip() or _VAGUE_EMPLOYER.search(job.company.strip()):
        red.append("The employer isn't named")
    if _PAY_TO_WORK.search(text):
        red.append("Asks you to pay for training, a kit or a certificate")
    if _CHAT_ONLY.search(text):
        red.append("Hiring happens over WhatsApp or Telegram, not an application")

    links = [a.get("url", "") for a in (job.apply_links or []) if a.get("url")] or [job.url]
    hosts = {_host(u) for u in links if u}
    on_ats = any(h.endswith(ats) for h in hosts for ats in ATS_HOSTS)
    if on_ats:
        v.good.append("Listed on the company’s careers system")
    if job.company_domain and any(h == job.company_domain or h.endswith("." + job.company_domain) for h in hosts):
        v.good.append("Apply link is on the company’s own website")

    if job.link_status == "ok":
        v.good.append("Apply link opened and the job is open")
    elif job.link_status == "unverified" and not on_ats:
        caution.append("The apply link couldn’t be opened to confirm it’s live")

    email = (job.recruiter_email or "").lower()
    if email and email.split("@")[-1] in FREE_MAIL:
        caution.append("The recruiter uses a personal email address")
    elif email and job.company_domain and email.endswith("@" + job.company_domain):
        v.good.append("Recruiter email matches the company domain")
    if _PHONE.search(job.description or ""):
        caution.append("Lists a personal phone number to contact")
    if _HYPE.search(text):
        caution.append("Uses pressure language (urgent hiring, limited seats, guarantees)")
    if re.search(r"\bintern", job.title or "", re.IGNORECASE) and (job.salary_max or 0) > 2_000_000:
        caution.append("Pay looks unusually high for an internship")
    if job.ghost_risk == "high":
        caution.append("Looks like a ghost job: " + "; ".join(job.ghost_reasons[:2]).lower())

    if red:
        v.status, v.reasons = "suspicious", red + caution
    elif caution:
        v.status, v.reasons = "caution", caution
    return v


class SecondOpinion(BaseModel):
    legitimate: bool = Field(description="False only if this looks like a scam or fake posting")
    concern: str = Field(description="If not legitimate, the main reason in under 15 words; otherwise empty")


SYSTEM = (
    "You check internship and entry-level job postings for scams in India and worldwide. Judge only from the posting. "
    "Say a posting is not legitimate only for clear signs: asking for money, chat-only hiring, no real employer, "
    "unrealistic pay for no work, or requests for ID documents before an interview. Unusual but plausible postings are legitimate."
)


async def second_opinion(job: Job, state: PipelineState) -> SecondOpinion | None:
    try:
        return await get_llm().structured(
            agent="verifier",
            tier="fast",
            system=SYSTEM,
            prompt=f"Employer: {job.company}\nTitle: {job.title}\nLocation: {job.location}\n\n{(job.description or '')[:3500]}",
            schema=SecondOpinion,
            ctx=ctx_of(state),
            max_tokens=400,
        )
    except (LLMUnavailable, LLMOutputError):
        return None


async def run_verifier(state: PipelineState) -> dict:
    async with agent_step(state, "verifier") as step:
        ids = [uuid.UUID(j) for j in state.get("new_job_ids", [])]
        now = datetime.now(UTC)
        async with session_scope() as s:
            jobs = (await s.execute(select(Job).where(Job.id.in_(ids)))).scalars().all()
            fresh = [j for j in jobs if j.legit_checked_at is None or j.legit_checked_at < now - RECHECK_AFTER]
            verdicts = {j.id: assess(j) for j in fresh}

            # The LLM only reviews the most doubtful few, and can only make a verdict stricter.
            doubtful = sorted((j for j in fresh if verdicts[j.id].status == "caution" and len(verdicts[j.id].reasons) >= 2), key=lambda j: -len(verdicts[j.id].reasons))
            for j in doubtful[:MAX_LLM_REVIEWS]:
                op = await second_opinion(j, state)
                if op and not op.legitimate:
                    verdicts[j.id].status = "suspicious"
                    verdicts[j.id].reasons.insert(0, op.concern.strip().rstrip(".") or "Reads like a scam posting")

            for j in fresh:
                v = verdicts[j.id]
                j.legit_status, j.legit_reasons, j.legit_checked_at = v.status, (v.reasons or v.good)[:5], now
            counts = {"verified": 0, "caution": 0, "suspicious": 0}
            for j in jobs:
                counts[j.legit_status or "verified"] += 1
            keep = [str(j.id) for j in jobs if j.legit_status != "suspicious"]

        step.detail = f"Checked {len(jobs)} job{'' if len(jobs) == 1 else 's'}: {counts['verified']} verified, {counts['caution']} need care, {counts['suspicious']} blocked as suspicious"
        await bump_stats(state["run_id"], verified=counts["verified"], caution=counts["caution"], suspicious=counts["suspicious"])
        return {"new_job_ids": keep, "done": ["verifier"]}

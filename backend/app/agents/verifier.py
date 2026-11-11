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
from app.models import Job, Verification
from app.services import scam_shield

LINK_RECHECKS = 15  # apply links re-opened per run when re-checking open matches
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
    shield: scam_shield.ShieldResult | None = None


SHIELD_VERDICT = {"verified": "Likely safe", "caution": "Suspicious", "suspicious": "Likely scam"}


def _posting_text(job: Job) -> str:
    return f"{job.company}\n{job.title}\n{job.description or ''}\n{job.recruiter_email or ''}"


def ghost_score(job: Job, now: datetime) -> int:
    """0 (clearly open) to 100 (almost certainly a ghost job): posting age, reposts, when a source last listed it,
    whether the company's ATS still shows it open, and whether it's on the company's own careers page."""
    score = 0
    if job.posted_at:
        age = (now - job.posted_at).days
        score += 30 if age > 60 else 20 if age > 30 else 0
    score += 25 if job.repost_count >= 3 else 15 if job.repost_count >= 2 else 0
    if job.last_seen_at and (now - job.last_seen_at).days > 3:
        score += 20  # no source has listed it for days
    hosts = {_host(a.get("url", "")) for a in (job.apply_links or [])} | {_host(job.url or "")}
    on_ats = any(h.endswith(ATS_HOSTS) for h in hosts if h)
    on_site = bool(job.company_domain) and any(h == job.company_domain or h.endswith("." + job.company_domain) for h in hosts if h)
    score += 40 if job.link_status == "dead" else 15 if job.link_status == "unverified" and not on_ats else 0
    if on_ats and job.link_status == "ok":
        score -= 10  # the ATS still lists it as open
    if not (on_ats or on_site):
        score += 10  # not on any careers page we can see
    if len(job.description or "") < 400:
        score += 10
    return max(0, min(100, score))


async def apply_verdict(s, job: Job, now: datetime, v: "Verdict | None" = None) -> Verdict:
    """Sets the job's verdict and records a verification row (with evidence: postings are public)."""
    v = v or assess(job)
    gs = ghost_score(job, now)
    sh = v.shield
    row = Verification(
        id=uuid.uuid4(), opportunity_id=job.id, source="pipeline", input_hash=scam_shield.input_hash(_posting_text(job), job.url or ""),
        verdict=SHIELD_VERDICT[v.status], score=max(sh.score if sh else 0, 70 if v.status == "suspicious" else 30 if v.status == "caution" else 0),
        checks=[*([{"id": c.id, "label": c.label, "status": c.status, "evidence": c.evidence[:2]} for c in sh.checks] if sh else []),
                *({"id": "verifier", "label": r, "status": "fail" if v.status == "suspicious" else "warn", "evidence": []} for r in v.reasons)],
        ghost_score=gs,
    )
    s.add(row)
    await s.flush()  # the row must exist before the job points at it
    job.verification_id = row.id
    job.ghost_score = gs
    job.legit_status, job.legit_reasons, job.legit_checked_at = v.status, (v.reasons or v.good)[:5], now
    return v


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

    # Scam Shield's checks (fees, UPI IDs, lookalike domains, task and fake-government scams, OTP requests...),
    # the same ones students run on WhatsApp offers. A job description mentioning payments in general (a fintech
    # role) isn't a demand for money, so a payment check only counts with an actual UPI ID.
    v.shield = scam_shield.analyze(_posting_text(job), job.url or "", known_company_domain=job.company_domain)
    for c in v.shield.checks:
        if c.status == "fail" and not (c.id == "upi" and not any("@" in e for e in c.evidence)):
            red.append(c.label)
        elif c.status == "warn" and c.weight >= 20 and c.id not in ("free_mail", "chat_only"):  # the rules above already cover those
            caution.append(c.label)
    red, caution = list(dict.fromkeys(red)), [x for x in dict.fromkeys(caution) if x not in red]

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


async def _recheck_open(state: PipelineState, step, match_ids: list[uuid.UUID], now: datetime) -> dict:
    """No new postings: re-open the apply links of your open matches (a closed listing is hidden before you spend
    time on it) and re-run the scam checks on any not checked recently."""
    import asyncio

    import httpx

    from app.models import JobMatch
    from app.sources.authenticity import FIRST_PARTY, check_link
    from app.sources.base import USER_AGENT

    async with session_scope() as s:
        rows = (await s.execute(select(JobMatch.id, Job).join(Job, Job.id == JobMatch.job_id).where(JobMatch.id.in_(match_ids)))).all()
    to_link = [j for _, j in rows if j.source not in FIRST_PARTY and j.url][:LINK_RECHECKS]
    sem = asyncio.Semaphore(8)

    async def one(client, j):
        async with sem:
            return j.id, await check_link(client, j.url)

    status: dict = {}
    if to_link:
        async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT}) as client:
            status = dict(await asyncio.gather(*(one(client, j) for j in to_link)))
    closed = suspicious = care = 0
    keep: list[str] = []
    async with session_scope() as s:
        for match_id, j0 in rows:
            j = await s.get(Job, j0.id)
            if status.get(j.id) == "dead":
                j.link_status = "dead"
                closed += 1
            elif status.get(j.id) == "ok":
                j.link_status = "ok"
            if j.legit_checked_at is None or j.legit_checked_at < now - RECHECK_AFTER:
                await apply_verdict(s, j, now, assess(j))
            suspicious += j.legit_status == "suspicious"
            care += j.legit_status == "caution"
            if j.link_status != "dead" and j.legit_status != "suspicious":
                keep.append(str(match_id))
    step.detail = (
        f"Re-checked your {len(rows)} open match{'es' if len(rows) != 1 else ''}: {len(status)} apply link{'s' if len(status) != 1 else ''} opened, "
        f"{closed} closed and hidden, {care} need care, {suspicious} blocked"
    )
    return {"recheck_match_ids": keep, "done": ["verifier"]}


async def run_verifier(state: PipelineState) -> dict:
    async with agent_step(state, "verifier") as step:
        ids = [uuid.UUID(j) for j in state.get("new_job_ids", [])]
        recheck = [uuid.UUID(m) for m in state.get("recheck_match_ids", [])] if not ids else []
        now = datetime.now(UTC)
        if recheck:
            return await _recheck_open(state, step, recheck, now)
        async with session_scope() as s:
            jobs = (await s.execute(select(Job).where(Job.id.in_(ids)))).scalars().all()
            fresh = [j for j in jobs if j.legit_checked_at is None or j.legit_checked_at < now - RECHECK_AFTER]
            verdicts = {j.id: assess(j) for j in fresh}

            # The ledger: a stipend far from what 3+ students report for this company asks for care (monthly figures only).
            from app.api.routes.ledger import market_check

            for j in fresh:
                if j.salary_max and j.salary_max < 300_000 and verdicts[j.id].status != "suspicious":
                    note = await market_check(s, j.company, j.salary_max)
                    if note:
                        verdicts[j.id].status = "caution"
                        verdicts[j.id].reasons.append(note)

            # The LLM only reviews the most doubtful few, and can only make a verdict stricter.
            doubtful = sorted((j for j in fresh if verdicts[j.id].status == "caution" and len(verdicts[j.id].reasons) >= 2), key=lambda j: -len(verdicts[j.id].reasons))
            for j in doubtful[:MAX_LLM_REVIEWS]:
                op = await second_opinion(j, state)
                if op and not op.legitimate:
                    verdicts[j.id].status = "suspicious"
                    verdicts[j.id].reasons.insert(0, op.concern.strip().rstrip(".") or "Reads like a scam posting")

            for j in fresh:
                await apply_verdict(s, j, now, verdicts[j.id])
            counts = {"verified": 0, "caution": 0, "suspicious": 0}
            for j in jobs:
                counts[j.legit_status or "verified"] += 1
            keep = [str(j.id) for j in jobs if j.legit_status != "suspicious"]

        step.detail = f"Checked {len(jobs)} job{'' if len(jobs) == 1 else 's'}: {counts['verified']} verified, {counts['caution']} need care, {counts['suspicious']} blocked as suspicious"
        await bump_stats(state["run_id"], verified=counts["verified"], caution=counts["caution"], suspicious=counts["suspicious"])
        if not keep and state.get("recheck_match_ids"):
            # Every new posting was blocked: the rest of the crew works on your open matches instead.
            first = step.detail
            out = await _recheck_open(state, step, [uuid.UUID(m) for m in state["recheck_match_ids"]], now)
            step.detail = f"{first} · {step.detail}"
            return {**out, "new_job_ids": []}
        return {"new_job_ids": keep, "done": ["verifier"]}

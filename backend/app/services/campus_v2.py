"""Campus v2 (F11): officer queries under row-level security, the drive-circular parser, eligibility notifications,
alumni referrals, and the transparency rollup."""

import re
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert

from app.config import settings
from app.db import session_scope
from app.logging import log
from app.models import AgentRun, ApprovalEvent, CampusDrive, Consent, Notification, OrgMember, Profile, TransparencyDaily, User, Verification
from app.services.campus import eligibility

_officer_role: bool | None = None


@asynccontextmanager
async def officer_scope(org_id):
    """A transaction in which Postgres itself hides every student of this college who hasn't an active college_share
    consent (profiles, job_matches, drive_statuses). Individual-level officer reads must go through here."""
    global _officer_role
    async with session_scope() as s:
        if _officer_role is None:
            _officer_role = bool((await s.execute(text("SELECT pg_has_role(current_user, 'jobpilot_officer', 'MEMBER') FROM pg_roles WHERE rolname = 'jobpilot_officer'"))).scalar())
        if _officer_role:
            await s.execute(text("SET LOCAL ROLE jobpilot_officer"))
        await s.execute(text("SELECT set_config('app.viewer_org', :o, true)"), {"o": str(org_id)})
        yield s


# ── Drive-circular parser ───────────────────────────────────────────────────────────────────────────────────────

BRANCHES = {
    "CSE": r"\b(cse|computer\s*(science|engineering|engg)|comp\.?\s*engg?|comp\b|cs\b)",
    "IT": r"\b(it\b|information\s*technology)",
    "ECE": r"\b(ece|electronics\s*(and|&)\s*communication|e\s*&\s*tc|entc|extc|electronics\s*(and|&)\s*tele)",
    "EEE": r"\b(eee|electrical\s*(and|&)\s*electronics)",
    "EE": r"\b(ee\b|electrical\s*engg?|electrical(?!\s*(and|&)))",
    "MECH": r"\b(mech(anical)?)\b",
    "CIVIL": r"\bcivil\b",
    "AIDS": r"\b(ai\s*(and|&)\s*ds|ai\s*&\s*data\s*science|artificial\s*intelligence\s*(and|&)\s*data\s*science)",
    "AIML": r"\b(ai\s*(and|&)?\s*ml|aiml|artificial\s*intelligence\s*(and|&)\s*machine\s*learning)",
    "CHEM": r"\bchemical\b",
    "MCA": r"\bmca\b",
}
_MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
_ROUND_WORDS = [
    ("aptitude", r"aptitude|online\s*(test|assessment)|written\s*test|\boa\b"),
    ("coding", r"coding\s*(round|test)|programming\s*test|hackerrank|hackerearth"),
    ("group discussion", r"group\s*discussion|\bgd\b"),
    ("technical interview", r"technical\s*(interview|round)|tech\s*interview|\bti\b"),
    ("hr interview", r"\bhr\s*(interview|round)?\b|managerial|hiring\s*manager"),
]


def _field(text: str, *labels: str) -> str | None:
    for label in labels:
        m = re.search(rf"(?im)^\s*[*•\-]?\s*(?:{label})\s*[:\-–]\s*(.+)$", text)
        if m:
            return m.group(1).strip(" *")
    return None


def _date(s: str, today: date) -> date | None:
    s = s.lower()
    m = re.search(r"(\d{1,2})(?:st|nd|rd|th)?[\s\-/.]*(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*[\s\-/.,]*(\d{4})?", s)
    if m:
        y = int(m.group(3)) if m.group(3) else today.year
        return date(y, _MONTHS[m.group(2)], int(m.group(1)))
    m = re.search(r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+(\d{1,2})(?:st|nd|rd|th)?,?\s*(\d{4})?", s)
    if m:
        y = int(m.group(3)) if m.group(3) else today.year
        return date(y, _MONTHS[m.group(1)], int(m.group(2)))
    m = re.search(r"\b(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})\b", s)
    if m:
        y = int(m.group(3))
        return date(y + 2000 if y < 100 else y, int(m.group(2)), int(m.group(1)))
    return None


def parse_circular(raw: str, today: date | None = None) -> dict:
    """Structured drive from a placement-cell circular (PDF text or a WhatsApp forward). Rules first; works offline."""
    today = today or datetime.now(UTC).date()
    t = raw.replace("\r", "")
    flat = re.sub(r"\s+", " ", t)

    company = _field(t, r"company(?:\s*name)?", r"organi[sz]ation", r"recruiter", "name of (?:the )?company", r"internship(?:\s*drive)?")
    if company and re.search(r"\d|opportunit", company, re.I):
        company = None
    if not company:
        # "Campus drive by Mphasis", "Placement Drive by Wipro": the name must start with a capital letter.
        m = re.search(r"(?i:drive|recruitment|hiring|placement)\s*(?i:drive)?\s*(?i:by|of)\s+([A-Z][\w&.\-]*(?:[ \t]+[A-Z][\w&.\-]*){0,3})", t)
        company = m.group(1).strip() if m else None
    if not company:
        # "Infosys is conducting a drive", "Dear all, KPIT Technologies is hiring interns."
        m = re.search(r"([A-Z][\w&.]+(?:[ \t]+[A-Z][\w&.]+){0,3})[ \t]+(?:is[ \t]+)?(?i:conducting|hiring|organi[sz]ing|visiting|recruiting|campus drive|off[- ]campus)", t)
        company = m.group(1) if m else None

    role = _field(t, "role", "profile", "position", "designation", "job role", "post")
    if not role:
        m = re.search(r"(?i)\bfor\s+(?:the\s+)?(?:role|position|post)\s+of\s+([^\n,.]+)", t) or re.search(r"(?i)\b((?:[A-Z][a-z]+\s){0,3}(?:Intern|Trainee|Engineer|Analyst|Developer)(?:\s*[-–]\s*\w+)?)\b", t)
        role = m.group(1).strip() if m else None

    comp = _field(t, "ctc", "stipend", "package", "salary", "compensation")
    if not comp:
        m = re.search(r"(?i)((?:₹|rs\.?|inr)\s*[\d,.]+\s*(?:lpa|lakh[s]?|l|k)?(?:\s*(?:per|/)\s*(?:month|annum|year|m))?|[\d.]+\s*lpa)", flat)
        comp = m.group(1).strip() if m else None

    elig: dict = {}
    m = re.search(r"(?i)(\d(?:\.\d{1,2})?)\s*(?:cgpa|cpi|sgpa|gpa|pointer)|(?:cgpa|cpi|gpa|pointer)\s*(?:of\s*)?(?:>=|≥|above|:|-|minimum|min\.?)?\s*(\d(?:\.\d{1,2})?)", flat)
    if m:
        elig["min_cgpa"] = float(m.group(1) or m.group(2))
    m = re.search(r"(?i)(\d{2})\s*%\s*(?:and above\s*)?(?:throughout|aggregate|in all|& above|or above|minimum)?", flat)
    if m:
        elig["min_percent"] = int(m.group(1))
    branch_text = _field(t, "branch(?:es)?", "eligible branch(?:es)?", "streams?", "departments?", "eligibility") or flat
    if re.search(r"(?i)all\s*branch|any\s*branch|all\s*(?:engineering\s*)?streams", branch_text):
        elig["branches"] = []
    else:
        elig["branches"] = [b for b, pat in BRANCHES.items() if re.search(pat, branch_text, re.I)]
    if re.search(r"(?i)no\s*(?:active|live|current)?\s*backlogs?|zero\s*backlogs?|without\s*(?:any\s*)?backlogs?", flat):
        elig["max_backlogs"] = 0
    else:
        m = re.search(r"(?i)(?:max(?:imum)?|upto|up to|<=|≤)\s*(\d)\s*(?:active\s*)?backlogs?|(\d)\s*(?:active\s*)?backlogs?\s*(?:allowed|permitted)", flat)
        if m:
            elig["max_backlogs"] = int(m.group(1) or m.group(2))
    years = re.findall(r"(?i)(20\d\d)\s*(?:batch|pass(?:ing)?[- ]?out|graduat)", flat)
    years += re.findall(r"(?i)(?:batch|pass(?:ing)?[- ]?out|graduating)\s*(?:year)?\s*(?:of|:|-)?\s*(20\d\d)", flat)
    for a, b in re.findall(r"(?i)(20\d\d)\s*(?:and|&|,|/)\s*(20\d\d)\s*(?:batch|pass)", flat):
        years += [a, b]
    elig["grad_years"] = sorted({int(y) for y in years})

    deadline_text = _field(t, r"last date(?: to (?:apply|register))?", r"registration (?:deadline|closes|last date)", "deadline", "apply by", "register by")
    if not deadline_text:
        m = re.search(r"(?i)(?:last date|deadline|register by|apply by|before)\s*(?:is|:|-)?\s*([^\n]{3,40})", t)
        deadline_text = m.group(1) if m else None
    register_by = _date(deadline_text, today) if deadline_text else None

    rounds_text = _field(t, r"selection process", r"rounds?", r"process", r"recruitment process") or flat
    rounds = []
    for name, pat in _ROUND_WORDS:
        m = re.search(pat, rounds_text, re.I)
        if m:
            rounds.append((m.start(), name))
    kind = "full_time" if re.search(r"(?i)\b(full[- ]time|fte|lpa|ctc)\b", flat) and not re.search(r"(?i)\bintern(ship)?\b", flat) else "internship"
    return {
        "company": (company or "").strip(" -–:|")[:200],
        "role": (role or "").strip(" -–:|")[:200],
        "kind": kind,
        "compensation": (comp or "")[:100],
        "eligibility": {k: v for k, v in elig.items() if v not in (None,)},
        "register_by": register_by.isoformat() if register_by else None,
        "rounds": [{"name": n, "type": n.split()[0]} for _, n in sorted(rounds)],
    }


async def notify_eligible(s, drive: CampusDrive) -> int:
    """Tells every consenting student of the college who meets the eligibility rules."""
    rows = (
        await s.execute(
            select(Profile)
            .join(OrgMember, OrgMember.user_id == Profile.user_id)
            .join(Consent, (Consent.user_id == Profile.user_id) & (Consent.purpose == "college_share") & Consent.withdrawn_at.is_(None))
            .where(OrgMember.org_id == drive.org_id, OrgMember.role == "student")
        )
    ).scalars().all()
    n = 0
    for p in rows:
        ok, _ = eligibility(drive, p.academics or {})
        if ok:
            when = f" Register by {drive.register_by:%d %b}." if drive.register_by else ""
            s.add(Notification(user_id=p.user_id, kind="campus_drive", title=f"You're eligible: {drive.company} · {drive.role}", body=f"Your placement cell posted a drive you qualify for.{when}"))
            n += 1
    return n


async def transparency_sweep(now: datetime | None = None, days: int = 35) -> int:
    """Daily: (re)computes the public transparency counts for each of the last `days` days. Aggregates only."""
    now = now or datetime.now(UTC)
    n = 0
    async with session_scope() as s:
        for i in range(1, days + 1):
            day = (now - timedelta(days=i)).date()
            start = datetime.combine(day, datetime.min.time(), UTC)
            end = start + timedelta(days=1)
            in_day = lambda col: (col >= start) & (col < end)  # noqa: E731
            verified, flagged = (
                await s.execute(select(func.count(), func.count().filter(Verification.verdict == "Likely scam")).where(Verification.source == "pipeline", in_day(Verification.created_at)))
            ).one()
            checks = (await s.execute(select(func.count()).where(Verification.source == "public", in_day(Verification.created_at)))).scalar_one()
            approved = (await s.execute(select(func.count()).where(ApprovalEvent.action == "approve", in_day(ApprovalEvent.created_at)))).scalar_one()
            avg_usd = (
                await s.execute(
                    select(func.avg(AgentRun.cost_usd)).join(User, User.id == AgentRun.user_id).where(User.is_demo.is_(False), AgentRun.status.in_(["completed", "awaiting_approval"]), in_day(AgentRun.created_at))
                )
            ).scalar_one()
            row = {"date": day, "postings_verified": verified, "scams_flagged": flagged, "sends_approved": approved, "scam_checks": checks, "avg_cost_inr": round(float(avg_usd) * settings.usd_inr_rate, 2) if avg_usd is not None else None}
            stmt = insert(TransparencyDaily).values(row)
            await s.execute(stmt.on_conflict_do_update(index_elements=[TransparencyDaily.date], set_={k: stmt.excluded[k] for k in row if k != "date"}))
            n += 1
    log.info("transparency.sweep", days=n)
    return n

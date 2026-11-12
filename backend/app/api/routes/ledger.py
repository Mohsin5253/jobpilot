"""Stipend & PPO ledger (F7).

Students who interned somewhere report the stipend, duration, mode, whether a PPO was offered and whether they were
paid on time, under the `ledger` consent. A report is verified by a one-time code sent to a college email address
(.ac.in / .edu.in / .edu), or by an offer letter that is stored encrypted only until a moderator checks it and then
deleted, keeping just its SHA-256. A company's numbers are shown only once 3 or more published reports exist
(k-anonymity), and outliers wait in a moderation queue first.
"""

import hashlib
import re
import secrets
import statistics
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select

from app.api.deps import AdminDep, RealUserDep, SessionDep, UserDep
from app.models import StipendReport
from app.security import _fernet
from app.services.consent import has
from app.services.mailer import send_system_email
from app.services.ratelimit import hit

router = APIRouter(prefix="/ledger", tags=["ledger"])
K_MIN = 3
COLLEGE_DOMAIN = re.compile(r"@[\w.-]+\.(ac\.in|edu\.in|edu)$", re.IGNORECASE)


def company_key(name: str) -> str:
    n = re.sub(r"\b(pvt|private|ltd|limited|llp|inc|technologies|technology|solutions|india)\b\.?", " ", name.lower())
    return re.sub(r"[^a-z0-9]+", " ", n).strip()


class ReportIn(BaseModel):
    company: str = Field(min_length=2, max_length=200)
    role: str = Field(default="", max_length=200)
    stipend: int = Field(ge=0, le=500_000)  # INR per month
    duration_months: int = Field(ge=1, le=24)
    mode: str = Field(pattern="^(remote|onsite|hybrid)$")
    ppo_offered: bool
    paid_on_time: bool


def _mine(r: StipendReport) -> dict:
    return {
        "id": str(r.id), "company": r.company, "role": r.role, "stipend": r.stipend, "duration_months": r.duration_months, "mode": r.mode,
        "ppo_offered": r.ppo_offered, "paid_on_time": r.paid_on_time, "verified_via": r.verified_via, "status": r.status, "created_at": r.created_at.isoformat(),
    }


async def _published(s, key: str) -> list[StipendReport]:
    return list((await s.execute(select(StipendReport).where(StipendReport.company_key == key, StipendReport.status == "published"))).scalars())


def _round(v: float, step: int = 1000) -> int:
    return int(round(v / step) * step)


def aggregate(rows: list[StipendReport]) -> dict | None:
    """None below k = 3: nothing about a company is shown until three students have reported. Above it, nothing can
    be traced back to one student by comparing the page before and after a report (differencing):
    - reports join the figures two at a time, so no two published states differ by a single student;
    - stipends are rounded to ₹1,000, the count is a band, and there's no exact minimum or maximum;
    - the middle-half range appears from 10 reports, rates (rounded to 10%) and work modes from 5, and a mode only
      when at least 2 students reported it."""
    if len(rows) < K_MIN:
        return None
    rows = sorted(rows, key=lambda r: (r.created_at or datetime.min.replace(tzinfo=UTC), str(r.id)))
    n = K_MIN + ((len(rows) - K_MIN) // 2) * 2
    rows = rows[:n]
    stipends = sorted(_round(r.stipend) for r in rows)
    q = statistics.quantiles(stipends, n=4) if n >= 10 else None
    modes = {m: sum(r.mode == m for r in rows) for m in {r.mode for r in rows}}
    return {
        "company": rows[0].company,
        "reports_band": "3–4" if n < 5 else "5–9" if n < 10 else "10+",
        "median_stipend": _round(statistics.median(stipends)),
        "stipend_range": [_round(q[0]), _round(q[2])] if q else None,
        "ppo_rate": round(sum(r.ppo_offered for r in rows) / n, 1) if n >= 5 else None,
        "paid_on_time_rate": round(sum(r.paid_on_time for r in rows) / n, 1) if n >= 5 else None,
        "modes": sorted(m for m, c in modes.items() if c >= 2) if n >= 5 else [],
    }


async def market_check(s, company: str, monthly_stipend: float | None) -> str | None:
    """For the Verifier: a stipend far from what students report for this company (only with k >= 3)."""
    if not monthly_stipend:
        return None
    agg = aggregate(await _published(s, company_key(company)))
    if not agg:
        return None
    med = agg["median_stipend"]
    if monthly_stipend < 0.5 * med:
        return f"Stipend is well below the ₹{med:,}/month students report for {agg['company']}"
    if monthly_stipend > 3 * med:
        return f"Stipend is far above the ₹{med:,}/month students report for {agg['company']}: check it's real"
    return None


@router.post("/reports", status_code=201)
async def create_report(body: ReportIn, user: RealUserDep, session: SessionDep) -> dict:
    if not await has(session, user.id, "ledger"):
        raise HTTPException(403, "Turn on “Add my stipend and PPO reports to the anonymous company ledger” in Settings → Privacy first")
    r = StipendReport(user_id=user.id, company=body.company.strip(), company_key=company_key(body.company), **body.model_dump(exclude={"company"}))
    session.add(r)
    await session.commit()
    return _mine(r)


@router.get("/reports")
async def my_reports(user: UserDep, session: SessionDep) -> list[dict]:
    rows = (await session.execute(select(StipendReport).where(StipendReport.user_id == user.id).order_by(StipendReport.created_at.desc()))).scalars()
    return [_mine(r) for r in rows]


class OtpStart(BaseModel):
    college_email: EmailStr


class OtpCheck(BaseModel):
    code: str = Field(min_length=6, max_length=6)


async def _own(session, user, report_id: str) -> StipendReport:
    r = await session.get(StipendReport, report_id)
    if r is None or r.user_id != user.id:
        raise HTTPException(404, "No such report")
    return r


@router.post("/reports/{report_id}/otp")
async def start_otp(report_id: str, body: OtpStart, user: RealUserDep, session: SessionDep) -> dict:
    """Sends a 6-digit code to a college address. The address itself isn't stored."""
    await hit("mail_verify", str(user.id))
    if not COLLEGE_DOMAIN.search(str(body.college_email)):
        raise HTTPException(422, "Use your college email (ending .ac.in, .edu.in or .edu)")
    r = await _own(session, user, report_id)
    code = f"{secrets.randbelow(1_000_000):06d}"
    r.otp_hash, r.otp_expires_at = hashlib.sha256(f"{r.id}:{code}".encode()).hexdigest(), datetime.now(UTC) + timedelta(minutes=15)
    await session.commit()
    sent = await send_system_email(str(body.college_email), "Your JobPilot verification code", f"Your code is {code}. It expires in 15 minutes.")
    if not sent:
        raise HTTPException(503, "Email isn't set up on this server yet. Upload your offer letter instead.")
    return {"detail": "Code sent"}


async def _publish_or_flag(session, r: StipendReport) -> None:
    rows = await _published(session, r.company_key)
    med = statistics.median([x.stipend for x in rows]) if len(rows) >= K_MIN else None
    outlier = r.stipend > 150_000 or r.stipend < 1_000 or (med is not None and not 0.33 * med <= r.stipend <= 3 * med)
    r.status = "flagged" if outlier else "published"


@router.post("/reports/{report_id}/otp/verify")
async def verify_otp(report_id: str, body: OtpCheck, user: RealUserDep, session: SessionDep) -> dict:
    r = await _own(session, user, report_id)
    ok = r.otp_hash and r.otp_expires_at and r.otp_expires_at > datetime.now(UTC) and secrets.compare_digest(r.otp_hash, hashlib.sha256(f"{r.id}:{body.code}".encode()).hexdigest())
    if not ok:
        raise HTTPException(422, "That code is wrong or has expired")
    r.verified_via, r.otp_hash, r.otp_expires_at = "college_email", None, None
    await _publish_or_flag(session, r)
    await session.commit()
    return _mine(r)


@router.post("/reports/{report_id}/offer-letter")
async def upload_letter(report_id: str, user: RealUserDep, session: SessionDep, file: UploadFile = File(...)) -> dict:
    """Stored encrypted until a moderator checks it; then deleted, keeping only its SHA-256."""
    r = await _own(session, user, report_id)
    data = await file.read(5 * 1024 * 1024 + 1)
    if len(data) > 5 * 1024 * 1024:
        raise HTTPException(413, "Up to 5 MB")
    r.doc_hash = hashlib.sha256(data).hexdigest()
    r.doc_enc = _fernet().encrypt(data)
    r.status = "pending"
    await session.commit()
    return _mine(r)


@router.get("/companies")
async def companies(session: SessionDep, q: str = "") -> list[dict]:
    """Public aggregates, only for companies with 3 or more published reports."""
    stmt = select(StipendReport.company_key).where(StipendReport.status == "published").group_by(StipendReport.company_key)
    if q.strip():
        stmt = stmt.where(StipendReport.company_key.like(f"%{company_key(q)}%"))
    keys = (await session.execute(stmt.limit(200))).scalars().all()
    out = [agg for k in keys if (agg := aggregate(await _published(session, k)))]
    rank = {"10+": 0, "5–9": 1, "3–4": 2}
    return sorted(out, key=lambda a: (rank[a["reports_band"]], a["company"].lower()))


@router.get("/admin/queue")
async def queue(_: AdminDep, session: SessionDep) -> list[dict]:
    rows = (await session.execute(select(StipendReport).where(StipendReport.status.in_(["flagged", "pending"]), (StipendReport.status == "flagged") | StipendReport.doc_enc.is_not(None)))).scalars()
    return [{**_mine(r), "has_letter": r.doc_enc is not None} for r in rows]


@router.get("/admin/reports/{report_id}/letter")
async def view_letter(report_id: str, _: AdminDep, session: SessionDep):
    from fastapi.responses import Response

    r = await session.get(StipendReport, report_id)
    if r is None or r.doc_enc is None:
        raise HTTPException(404, "No letter")
    return Response(_fernet().decrypt(r.doc_enc), media_type="application/octet-stream", headers={"cache-control": "no-store"})


class Decision(BaseModel):
    approve: bool


@router.post("/admin/reports/{report_id}")
async def moderate(report_id: str, body: Decision, _: AdminDep, session: SessionDep) -> dict:
    r = await session.get(StipendReport, report_id)
    if r is None:
        raise HTTPException(404, "No such report")
    if r.doc_enc is not None:
        r.doc_enc = None  # checked: the letter is deleted, its hash stays
        if body.approve:
            r.verified_via = "offer_letter"
    r.status = "published" if body.approve else "rejected"
    await session.commit()
    return _mine(r)

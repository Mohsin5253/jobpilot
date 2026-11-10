"""Data-principal rights under India's DPDP Act: access, correction, erasure, grievance and nomination.

Access (export), correction (Settings) and erasure (delete account) are self-service and immediate. This adds a
written request channel with a 30-day response target, for anything self-service doesn't cover, plus a public
grievance form for people without an account. Admins answer requests from /admin.
"""

from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select

from app.api.deps import AdminDep, RealUserDep, SessionDep, UserDep
from app.logging import log
from app.models import RightsRequest, User
from app.services.mailer import send_system_email
from app.services.ratelimit import client_ip, hit

router = APIRouter(tags=["rights"])

SLA = timedelta(days=30)
Kind = Literal["access", "correction", "erasure", "grievance", "nomination", "withdrawal"]

SELF_SERVICE = {
    "access": "Settings → Your data → Export downloads everything now.",
    "correction": "Edit your resume, skills and preferences in Settings at any time.",
    "erasure": "Settings → Your data → Delete account removes everything at once.",
    "withdrawal": "Settings → Privacy & consent: switch a purpose off and it stops at once.",
}


class RequestIn(BaseModel):
    kind: Kind
    details: str = Field(default="", max_length=4000)


class GrievanceIn(BaseModel):
    email: EmailStr
    details: str = Field(min_length=10, max_length=4000)


def _out(r: RightsRequest) -> dict:
    return {
        "id": str(r.id), "kind": r.kind, "details": r.details, "status": r.status, "response": r.response,
        "created_at": r.created_at.isoformat(), "due_at": r.due_at.isoformat(), "resolved_at": r.resolved_at.isoformat() if r.resolved_at else None,
    }


@router.get("/rights")
async def my_requests(user: UserDep, session: SessionDep) -> dict:
    rows = (await session.execute(select(RightsRequest).where(RightsRequest.user_id == user.id).order_by(RightsRequest.created_at.desc()))).scalars().all()
    return {"self_service": SELF_SERVICE, "sla_days": SLA.days, "requests": [_out(r) for r in rows]}


@router.post("/rights", status_code=201)
async def create_request(body: RequestIn, user: RealUserDep, session: SessionDep) -> dict:
    await hit("rights", str(user.id))
    now = datetime.now(UTC)
    r = RightsRequest(user_id=user.id, contact_email=user.email, kind=body.kind, details=body.details.strip(), created_at=now, due_at=now + SLA)
    session.add(r)
    await session.commit()
    log.info("rights.request", kind=body.kind)  # no personal data in logs
    return _out(r)


@router.post("/public/grievance", status_code=201)
async def public_grievance(body: GrievanceIn, request: Request, session: SessionDep) -> dict:
    """For anyone, account or not (e.g. a recruiter or someone whose data they think we hold)."""
    await hit("rights", client_ip(request))
    now = datetime.now(UTC)
    r = RightsRequest(contact_email=str(body.email).lower(), kind="grievance", details=body.details.strip(), created_at=now, due_at=now + SLA)
    session.add(r)
    await session.commit()
    await send_system_email(str(body.email), "We received your privacy request", f"Thanks for writing to JobPilot. We'll reply by {r.due_at:%d %B %Y}.\n\nReference: {r.id}")
    return {"id": str(r.id), "due_at": r.due_at.isoformat()}


@router.get("/admin/rights")
async def admin_list(_: AdminDep, session: SessionDep) -> list[dict]:
    rows = (await session.execute(select(RightsRequest).order_by(RightsRequest.status.desc(), RightsRequest.due_at))).scalars().all()
    return [{**_out(r), "contact_email": r.contact_email, "overdue": r.status == "open" and r.due_at < datetime.now(UTC)} for r in rows]


class ResolveIn(BaseModel):
    response: str = Field(min_length=1, max_length=4000)


@router.post("/admin/rights/{request_id}/resolve")
async def admin_resolve(request_id: str, body: ResolveIn, _: AdminDep, session: SessionDep) -> dict:
    r = await session.get(RightsRequest, request_id)
    if r is None:
        raise HTTPException(404, "No such request")
    r.status, r.response, r.resolved_at = "resolved", body.response.strip(), datetime.now(UTC)
    await session.commit()
    to = r.contact_email or ((await session.get(User, r.user_id)).email if r.user_id else "")
    if to:
        await send_system_email(to, "Your JobPilot privacy request", f"{r.response}\n\nReference: {r.id}")
    return _out(r)

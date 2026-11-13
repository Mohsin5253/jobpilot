"""Campus portal API, for verified college staff only.

  /api/campus/staff-join/*      a signed-in user becomes *pending* staff: valid staff code (locks after 5 wrong tries)
                                + institutional email on an allowed domain (personal domains never) confirmed by a
                                one-time code. No data access until the TPO / Principal approves.
  /api/campus/staff-session     opens the portal: mints the staff token (campus, role, status, account version);
                                TPO and Principal need a one-time code first (2FA). Every login is audit-logged.
  /api/campus/staff/**          everything else: active, approved staff only (StaffDep), every query under row-level
                                security (staff_session), every individual view / approval / verification / export
                                audit-logged.
Students are refused at every step (403), whatever code or URL they have.
"""

import csv
import io
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, or_, select, text, update

from app.api.deps import AdminDep, RealUserDep, UserDep
from app.campus import jobs as cjobs
from app.campus import otp
from app.campus.access import STAFF_ROLES, TWO_FACTOR, StaffDep, audit, mint_staff_token, require, staff_session
from app.campus.ids import uuid7
from app.campus.models import (
    Batch, Campus, CampusDegree, CampusJob, CampusMembership, CampusRollup, CapacityAllocation, CustomField, Degree, Department, Field as FieldRow,
    Institution, Program, RosterStudent, StaffAssignment, StudentAchievement,
)
from app.campus.rules import RuleError, validate
from app.db import session_scope
from app.models import CampusDrive, Notification, Organization, User
from app.services.placement import hash_code, new_staff_code
from app.services.ratelimit import client_ip, hit

router = APIRouter(prefix="/campus", tags=["campus-portal"])
JOIN_ROLES = ("hod", "faculty", "coordinator")


def _uuid(v: str) -> uuid.UUID:
    try:
        return uuid.UUID(v)
    except ValueError as exc:
        raise HTTPException(404, "Not found") from exc


# =============================== joining as staff ===============================


class JoinStart(BaseModel):
    code: str = Field(min_length=6, max_length=40)
    email: EmailStr


@router.post("/staff-join/start")
async def staff_join_start(body: JoinStart, user: RealUserDep, request: Request) -> dict:
    ip = client_ip(request)
    if await otp.locked(user.id, ip):
        raise HTTPException(429, "Too many wrong staff codes. Try again in 15 minutes.")
    async with session_scope() as s:
        campus = (await s.execute(select(Campus).where(Campus.staff_code_hash == hash_code(body.code)))).scalar_one_or_none()
        if campus is None or (campus.staff_code_expires_at and campus.staff_code_expires_at < datetime.now(UTC)):
            await otp.record_failure(user.id, ip)
            raise HTTPException(403, "That staff code isn't valid. Ask your TPO for the current code.")
        email = str(body.email).lower()
        if otp.personal(email):
            raise HTTPException(422, "Use your institutional email, not a personal address (Gmail, Yahoo, Outlook, Rediffmail...)")
        if not campus.allowed_email_domains:
            raise HTTPException(409, f"{campus.name} hasn't set its staff email domain yet. Ask your TPO to add it in Campus settings.")
        if not otp.domain_allowed(email, campus.allowed_email_domains):
            raise HTTPException(422, f"Use your {' or '.join('@' + d for d in campus.allowed_email_domains)} email")
        existing = (await s.execute(select(CampusMembership).where(CampusMembership.campus_id == campus.id, CampusMembership.user_id == user.id, CampusMembership.kind == "staff"))).scalar_one_or_none()
        if existing and existing.status in ("active", "pending"):
            raise HTTPException(409, "You've already joined this college as staff" + (" (waiting for approval)" if existing.status == "pending" else ""))
        campus_id, campus_name = campus.id, campus.name
        structure = await _structure(s, campus_id)
    await otp.issue(user.id, email, "staff_email", campus_id)
    return {"campus": campus_name, "otp_sent_to": email, **structure}


async def _structure(s, campus_id: uuid.UUID) -> dict:
    """Names only: what a joining staff member picks their departments, programmes and batches from."""
    depts = (await s.execute(select(Department).where(Department.campus_id == campus_id).order_by(Department.name))).scalars().all()
    progs = (await s.execute(select(Program, Degree).join(Degree, Degree.id == Program.degree_id).where(Program.campus_id == campus_id))).all()
    bats = (await s.execute(select(Batch).where(Batch.campus_id == campus_id).order_by(Batch.admission_year.desc()))).scalars().all()
    return {
        "departments": [{"id": str(d.id), "name": d.name} for d in depts],
        "programs": [{"id": str(p.id), "department_id": str(p.department_id), "name": f"{d.abbreviation} {p.specialisation}".strip()} for p, d in progs],
        "batches": [{"id": str(b.id), "program_id": str(b.program_id), "name": f"{b.admission_year}–{b.graduation_year}"} for b in bats],
    }


async def sync_legacy(s, campus_id: uuid.UUID, user_id: uuid.UUID, role: str | None, department: str = "") -> None:
    """Keep the v1 member row (pipeline board, drives) in step: one college per account there, so another college's
    row is never overwritten."""
    from app.models import OrgMember

    m = (await s.execute(select(OrgMember).where(OrgMember.user_id == user_id))).scalar_one_or_none()
    if role is None:
        if m and m.org_id == campus_id:
            await s.delete(m)
        return
    legacy = {"tpo": "tpo", "principal": "tpo", "hod": "hod", "faculty": "teacher", "coordinator": "teacher", "student": "student"}.get(role, "teacher")
    if m is None:
        s.add(OrgMember(org_id=campus_id, user_id=user_id, role=legacy, department=department[:120]))
    elif m.org_id == campus_id:
        m.role, m.department = legacy, department[:120] or m.department


class JoinVerify(BaseModel):
    otp: str = Field(min_length=6, max_length=6)
    role: Literal["hod", "faculty", "coordinator"]
    department_ids: list[uuid.UUID] = Field(default_factory=list, max_length=10)
    program_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)
    batch_ids: list[uuid.UUID] = Field(default_factory=list, max_length=40)


@router.post("/staff-join/verify")
async def staff_join_verify(body: JoinVerify, user: RealUserDep) -> dict:
    """Creates a *pending* staff membership and pending assignments. A student membership at the same campus stays a
    separate row: it never becomes staff, and the portal treats the two as different people."""
    row = await otp.check(user.id, "staff_email", body.otp)
    campus_id = row.campus_id
    async with session_scope() as s:
        campus = await s.get(Campus, campus_id)
        depts = {d.id for d in (await s.execute(select(Department).where(Department.campus_id == campus_id))).scalars()}
        progs = {p.id: p for p in (await s.execute(select(Program).where(Program.campus_id == campus_id))).scalars()}
        bats = {b.id: b for b in (await s.execute(select(Batch).where(Batch.campus_id == campus_id))).scalars()}
        if not set(body.department_ids) <= depts or not set(body.program_ids) <= set(progs) or not set(body.batch_ids) <= set(bats):
            raise HTTPException(422, "Pick departments, programmes and batches of this college")
        if body.role == "hod" and not body.department_ids:
            raise HTTPException(422, "An HOD picks their department(s)")
        m = (await s.execute(select(CampusMembership).where(CampusMembership.campus_id == campus_id, CampusMembership.user_id == user.id, CampusMembership.kind == "staff"))).scalar_one_or_none()
        if m is None:
            m = CampusMembership(campus_id=campus_id, id=uuid7(), institution_id=campus.institution_id, user_id=user.id, kind="staff")
            s.add(m)
        m.role, m.status, m.email_verified = body.role, "pending", True
        for d in body.department_ids:
            s.add(StaffAssignment(id=uuid7(), campus_id=campus_id, user_id=user.id, role=body.role, department_id=d))
        for p in body.program_ids:
            s.add(StaffAssignment(id=uuid7(), campus_id=campus_id, user_id=user.id, role=body.role, department_id=progs[p].department_id, program_id=p))
        for b in body.batch_ids:
            prog = progs.get(bats[b].program_id)
            s.add(StaffAssignment(id=uuid7(), campus_id=campus_id, user_id=user.id, role=body.role, department_id=prog.department_id if prog else None, program_id=bats[b].program_id, batch_id=b))
        tpos = (await s.execute(select(CampusMembership.user_id).where(CampusMembership.campus_id == campus_id, CampusMembership.kind == "staff", CampusMembership.status == "active", CampusMembership.role.in_(["tpo", "principal"])))).scalars().all()
        for t in tpos:
            s.add(Notification(user_id=t, kind="campus", title="Staff waiting for approval", body=f"{user.name or user.email} asked to join as {body.role}. Review it in the Campus portal."))
        if user.email.lower() == row.email:
            u = await s.get(User, user.id)
            u.email_verified_at = u.email_verified_at or datetime.now(UTC)
    return {"status": "pending", "detail": "Your institutional email is confirmed. Your TPO or Principal approves you next; until then the portal shows no student data."}


# =============================== opening the portal ===============================


class SessionIn(BaseModel):
    campus_id: uuid.UUID | None = None
    otp: str | None = Field(default=None, min_length=6, max_length=6)


async def _staff_membership(user_id: uuid.UUID, campus_id: uuid.UUID | None) -> CampusMembership:
    async with session_scope() as s:
        q = select(CampusMembership).where(CampusMembership.user_id == user_id, CampusMembership.kind == "staff")
        if campus_id:
            q = q.where(CampusMembership.campus_id == campus_id)
        rows = (await s.execute(q)).scalars().all()
    active = [m for m in rows if m.status == "active" and m.role in STAFF_ROLES]
    if not active:
        if any(m.status == "pending" for m in rows):
            raise HTTPException(403, "Your staff account is waiting for your TPO or Principal to approve it")
        raise HTTPException(403, "The Campus portal is for approved college staff only")
    return active[0]


@router.post("/staff-session/otp")
async def staff_session_otp(body: SessionIn, user: RealUserDep) -> dict:
    """TPO and Principal: a one-time code to the account's email before the portal opens (2FA)."""
    m = await _staff_membership(user.id, body.campus_id)
    if m.role not in TWO_FACTOR:
        return {"needed": False}
    await hit("mail_verify", str(user.id))
    await otp.issue(user.id, user.email, "staff_login", m.campus_id)
    return {"needed": True, "sent_to": user.email}


@router.post("/staff-session")
async def staff_session_open(body: SessionIn, user: RealUserDep, response: Response) -> dict:
    m = await _staff_membership(user.id, body.campus_id)
    if m.role in TWO_FACTOR:
        if not body.otp:
            raise HTTPException(428, "Enter the code we emailed you")
        await otp.check(user.id, "staff_login", body.otp)
    token = mint_staff_token(user, m.id, m.campus_id, m.role, m.status)
    from app.config import settings

    response.set_cookie("jp_staff", token, httponly=True, secure=settings.cookie_secure, samesite="lax", max_age=12 * 3600, path="/")
    async with session_scope() as s:
        from app.campus.models import StaffAudit

        s.add(StaffAudit(id=uuid7(), campus_id=m.campus_id, actor_user_id=user.id, action="login", detail={"role": m.role}))
    return {"staff_token": token, "campus_id": str(m.campus_id), "role": m.role}


@router.post("/staff-session/close", status_code=204)
async def staff_session_close(response: Response) -> None:
    response.delete_cookie("jp_staff", path="/")


@router.get("/staff/access")
async def staff_access(ctx: StaffDep) -> dict:
    """For the website's middleware: 200 only for an active, approved staff session."""
    return {"ok": True, "role": ctx.role, "campus_id": str(ctx.campus_id)}


# =============================== me, settings, staff code ===============================


async def _campus(campus_id: uuid.UUID) -> Campus:
    async with session_scope() as s:
        return await s.get(Campus, campus_id)


@router.get("/staff/me")
async def staff_me(ctx: StaffDep) -> dict:
    c = await _campus(ctx.campus_id)
    async with session_scope() as s:
        names = {d.id: d.name for d in (await s.execute(select(Department).where(Department.campus_id == ctx.campus_id))).scalars()}
    return {
        "campus": {"id": str(c.id), "name": c.name, "city": c.city, "state": c.state, "student_id_label": c.student_id_label, "pending_subjects_label": c.pending_subjects_label,
                   "score_scale": c.score_scale, "term_type": c.term_type, "allowed_email_domains": c.allowed_email_domains, "locale": c.locale},
        "role": ctx.role, "whole_campus": ctx.whole_campus,
        "scope": {"departments": [{"id": str(d), "name": names.get(d, "")} for d in ctx.dept_ids], "programs": [str(p) for p in ctx.program_ids], "batches": [str(b) for b in ctx.batch_ids]},
    }


class SettingsIn(BaseModel):
    allowed_email_domains: list[str] | None = Field(default=None, max_length=10)
    student_id_label: str | None = Field(default=None, max_length=40)
    pending_subjects_label: str | None = Field(default=None, max_length=40)
    score_scale: dict | None = None
    score_formula: str | None = Field(default=None, max_length=500)
    term_type: Literal["annual", "semester", "trimester", "modular"] | None = None
    locale: str | None = Field(default=None, max_length=10)
    custom_fields: list[dict] | None = Field(default=None, max_length=30)


SCALE_TYPES = {"cgpa", "gpa", "percentage", "division", "letter", "pass_fail"}


@router.put("/staff/settings")
async def staff_settings(body: SettingsIn, ctx: StaffDep) -> dict:
    require(ctx, "tpo", "principal")
    async with session_scope() as s:
        c = await s.get(Campus, ctx.campus_id)
        if body.allowed_email_domains is not None:
            doms = [d.strip().lower().lstrip("@") for d in body.allowed_email_domains if d.strip()]
            bad = [d for d in doms if d in otp.PERSONAL_DOMAINS or "." not in d]
            if bad:
                raise HTTPException(422, f"Not an institutional domain: {', '.join(bad)}")
            c.allowed_email_domains = doms
        for k in ("student_id_label", "pending_subjects_label", "score_formula", "term_type", "locale"):
            v = getattr(body, k)
            if v is not None:
                setattr(c, k, v.strip() or None if k == "pending_subjects_label" else v.strip())
        if body.score_scale is not None:
            t = body.score_scale.get("type")
            if t not in SCALE_TYPES:
                raise HTTPException(422, f"Scale type must be one of {', '.join(sorted(SCALE_TYPES))}")
            if t in ("cgpa", "gpa", "percentage") and not isinstance(body.score_scale.get("max"), (int, float)):
                raise HTTPException(422, "Give the scale's maximum (e.g. 10, 4 or 100), exactly as your college uses it")
            c.score_scale = {"type": t, "max": body.score_scale.get("max"), "labels": body.score_scale.get("labels") or []}
        if body.custom_fields is not None:
            await s.execute(text("DELETE FROM campus_custom_fields WHERE campus_id = :c"), {"c": c.id})
            for f in body.custom_fields:
                key = "".join(ch for ch in str(f.get("key", "")).lower().replace(" ", "_") if ch.isalnum() or ch == "_")[:40]
                if key:
                    s.add(CustomField(id=uuid7(), campus_id=c.id, key=key, label=str(f.get("label") or key)[:120], type=f.get("type") if f.get("type") in ("yes_no", "number", "text") else "yes_no"))
    await audit(ctx, "settings")
    return {"ok": True}


class CodeIn(BaseModel):
    expires_in_days: int | None = Field(default=30, ge=1, le=365)


@router.post("/staff/staff-code")
async def rotate_staff_code(body: CodeIn, ctx: StaffDep) -> dict:
    """A new staff code, shown once; the old one stops working."""
    require(ctx, "tpo", "principal")
    code = new_staff_code()
    async with session_scope() as s:
        c = await s.get(Campus, ctx.campus_id)
        c.staff_code_hash = hash_code(code)
        c.staff_code_expires_at = datetime.now(UTC) + timedelta(days=body.expires_in_days) if body.expires_in_days else None
        org = await s.get(Organization, ctx.campus_id)
        if org:
            org.staff_code_hash, org.staff_code_set_at = c.staff_code_hash, datetime.now(UTC)
    await audit(ctx, "staff_code")
    return {"code": code, "expires_at": c.staff_code_expires_at.isoformat() if c.staff_code_expires_at else None}


# =============================== staff approvals and assignments ===============================


@router.get("/staff/members")
async def staff_members(ctx: StaffDep, status: str = "pending") -> list[dict]:
    require(ctx, "tpo", "principal", "hod")
    async with staff_session(ctx) as s:
        rows = (
            await s.execute(
                select(CampusMembership, User).join(User, User.id == CampusMembership.user_id)
                .where(CampusMembership.campus_id == ctx.campus_id, CampusMembership.kind == "staff", CampusMembership.status == status)
                .order_by(CampusMembership.created_at.desc()).limit(200)
            )
        ).all()
        assigns = (await s.execute(select(StaffAssignment).where(StaffAssignment.campus_id == ctx.campus_id))).scalars().all()
    by_user: dict = {}
    for a in assigns:
        by_user.setdefault(a.user_id, []).append({"id": str(a.id), "department_id": str(a.department_id) if a.department_id else None, "program_id": str(a.program_id) if a.program_id else None,
                                                   "batch_id": str(a.batch_id) if a.batch_id else None, "status": a.status})
    return [{"membership_id": str(m.id), "user_id": str(u.id), "name": u.name or u.email.split("@")[0], "email": u.email, "role": m.role, "status": m.status,
             "email_verified": m.email_verified, "requested_at": m.created_at.isoformat(), "assignments": by_user.get(u.id, [])} for m, u in rows]


class MemberDecision(BaseModel):
    action: Literal["approve", "deactivate", "role"]
    role: Literal["tpo", "principal", "hod", "faculty", "coordinator"] | None = None


@router.post("/staff/members/{membership_id}")
async def decide_member(membership_id: str, body: MemberDecision, ctx: StaffDep) -> dict:
    """Approve a pending staff member (TPO / Principal), deactivate one (ends their sessions at once), or change a role.
    Only a TPO or Principal makes someone TPO or Principal; nobody approves or promotes themselves."""
    require(ctx, "tpo", "principal")
    mid = _uuid(membership_id)
    async with session_scope() as s:
        m = (await s.execute(select(CampusMembership).where(CampusMembership.campus_id == ctx.campus_id, CampusMembership.id == mid, CampusMembership.kind == "staff"))).scalar_one_or_none()
        if m is None:
            raise HTTPException(404, "No such staff member at your college")
        if m.user_id == ctx.user_id:
            raise HTTPException(403, "You can't approve, deactivate or promote yourself")
        if body.action == "approve":
            if not m.email_verified:
                raise HTTPException(409, "Their institutional email isn't confirmed yet")
            m.status = "active"
            await s.execute(update(StaffAssignment).where(StaffAssignment.campus_id == ctx.campus_id, StaffAssignment.user_id == m.user_id, StaffAssignment.status == "pending")
                            .values(status="approved", approved_by=ctx.user_id, approved_at=datetime.now(UTC)))
            dept = (await s.execute(select(Department.name).join(StaffAssignment, StaffAssignment.department_id == Department.id).where(StaffAssignment.campus_id == ctx.campus_id, StaffAssignment.user_id == m.user_id).limit(1))).scalar_one_or_none()
            await sync_legacy(s, ctx.campus_id, m.user_id, m.role, dept or "")
        elif body.action == "deactivate":
            m.status = "deactivated"
            u = await s.get(User, m.user_id)
            u.token_version += 1  # every session of theirs ends now: the next request is a 401
            await s.execute(update(StaffAssignment).where(StaffAssignment.campus_id == ctx.campus_id, StaffAssignment.user_id == m.user_id).values(status="revoked"))
            await sync_legacy(s, ctx.campus_id, m.user_id, None)
        else:
            if not body.role:
                raise HTTPException(422, "Pick the new role")
            m.role = body.role
        subject = m.user_id
    from app.campus.access import forget_scope

    forget_scope(subject)
    await audit(ctx, f"staff_{body.action}", subject, role=body.role)
    return {"ok": True}


class AssignmentIn(BaseModel):
    department_id: uuid.UUID | None = None
    program_id: uuid.UUID | None = None
    batch_id: uuid.UUID | None = None


@router.post("/staff/assignments", status_code=201)
async def request_assignment(body: AssignmentIn, ctx: StaffDep) -> dict:
    """Ask for another department / programme / batch. Pending until an HOD (their department) or the TPO approves."""
    if not (body.department_id or body.program_id or body.batch_id):
        raise HTTPException(422, "Pick a department, programme or batch")
    async with session_scope() as s:
        dept = body.department_id
        if body.batch_id:
            b = await s.get(Batch, body.batch_id)
            if b is None or b.campus_id != ctx.campus_id:
                raise HTTPException(404, "No such batch")
            body.program_id = b.program_id
        if body.program_id:
            p = await s.get(Program, body.program_id)
            if p is None or p.campus_id != ctx.campus_id:
                raise HTTPException(404, "No such programme")
            dept = p.department_id
        if dept and (await s.get(Department, dept)).campus_id != ctx.campus_id:
            raise HTTPException(404, "No such department")
        a = StaffAssignment(id=uuid7(), campus_id=ctx.campus_id, user_id=ctx.user_id, role=ctx.role, department_id=dept, program_id=body.program_id, batch_id=body.batch_id)
        s.add(a)
    return {"id": str(a.id), "status": "pending"}


@router.get("/staff/assignments")
async def pending_assignments(ctx: StaffDep) -> list[dict]:
    require(ctx, "tpo", "principal", "hod")
    async with session_scope() as s:
        q = select(StaffAssignment, User).join(User, User.id == StaffAssignment.user_id).where(StaffAssignment.campus_id == ctx.campus_id, StaffAssignment.status == "pending")
        if not ctx.whole_campus:
            q = q.where(StaffAssignment.department_id.in_(ctx.dept_ids or [uuid.UUID(int=0)]))
        rows = (await s.execute(q.limit(300))).all()
    return [{"id": str(a.id), "name": u.name or u.email, "role": a.role, "department_id": str(a.department_id) if a.department_id else None,
             "program_id": str(a.program_id) if a.program_id else None, "batch_id": str(a.batch_id) if a.batch_id else None} for a, u in rows]


@router.post("/staff/assignments/{assignment_id}")
async def decide_assignment(assignment_id: str, approve: bool, ctx: StaffDep) -> dict:
    require(ctx, "tpo", "principal", "hod")
    async with session_scope() as s:
        a = await s.get(StaffAssignment, _uuid(assignment_id))
        if a is None or a.campus_id != ctx.campus_id or a.status != "pending":
            raise HTTPException(404, "No such pending assignment")
        if a.user_id == ctx.user_id:
            raise HTTPException(403, "Someone else has to approve your own assignment")
        if not ctx.whole_campus and a.department_id not in ctx.dept_ids:
            raise HTTPException(403, "An HOD approves assignments in their own department only")
        a.status, a.approved_by, a.approved_at = ("approved" if approve else "revoked"), ctx.user_id, datetime.now(UTC)
        subject = a.user_id
    from app.campus.access import forget_scope

    forget_scope(subject)
    await audit(ctx, "assignment_" + ("approve" if approve else "reject"), subject, assignment_id=assignment_id)
    return {"ok": True}


# =============================== setup: degrees, departments, programmes, batches, capacity ===============================


@router.get("/staff/setup")
async def setup_state(ctx: StaffDep) -> dict:
    async with staff_session(ctx) as s:
        offered = (await s.execute(select(Degree).join(CampusDegree, CampusDegree.degree_id == Degree.id).where(CampusDegree.campus_id == ctx.campus_id))).scalars().all()
        depts = (await s.execute(select(Department).where(Department.campus_id == ctx.campus_id).order_by(Department.name))).scalars().all()
        progs = (await s.execute(select(Program).where(Program.campus_id == ctx.campus_id))).scalars().all()
        bats = (await s.execute(select(Batch).where(Batch.campus_id == ctx.campus_id).order_by(Batch.admission_year.desc()))).scalars().all()
        fields = (await s.execute(select(FieldRow).order_by(FieldRow.code))).scalars().all()
        customs = (await s.execute(select(CustomField).where(CustomField.campus_id == ctx.campus_id))).scalars().all()
    return {
        "degrees": [_deg(d) for d in offered],
        "departments": [{"id": str(d.id), "name": d.name, "native_name": d.native_name} for d in depts],
        "programs": [{"id": str(p.id), "department_id": str(p.department_id), "degree_id": str(p.degree_id), "field_code": p.field_code, "specialisation": p.specialisation,
                      "duration_years": float(p.duration_years) if p.duration_years else None, "term_type": p.term_type, "intake_per_year": p.intake_per_year} for p in progs],
        "batches": [{"id": str(b.id), "program_id": str(b.program_id), "admission_year": b.admission_year, "graduation_year": b.graduation_year, "current_term": b.current_term} for b in bats],
        "fields": [{"code": f.code, "level": f.level, "parent": f.parent_code, "name": f.name} for f in fields],
        "custom_fields": [{"key": c.key, "label": c.label, "type": c.type} for c in customs],
    }


def _deg(d: Degree) -> dict:
    return {"id": str(d.id), "name": d.name, "abbreviation": d.abbreviation, "isced_level": d.isced_level, "typical_years": float(d.typical_years) if d.typical_years else None,
            "country": d.country_code, "custom": d.campus_id is not None}


@router.get("/staff/degrees")
async def search_degrees(ctx: StaffDep, q: str = "") -> list[dict]:
    async with session_scope() as s:
        stmt = select(Degree).where(or_(Degree.campus_id.is_(None), Degree.campus_id == ctx.campus_id))
        if q.strip():
            like = f"%{q.strip()}%"
            stmt = stmt.where(or_(Degree.name.ilike(like), Degree.abbreviation.ilike(like)))
        rows = (await s.execute(stmt.order_by(Degree.isced_level, Degree.abbreviation).limit(60))).scalars().all()
    return [_deg(d) for d in rows]


class OfferedIn(BaseModel):
    degree_ids: list[uuid.UUID] = Field(max_length=300)


@router.put("/staff/degrees/offered")
async def set_offered(body: OfferedIn, ctx: StaffDep) -> dict:
    require(ctx, "tpo", "principal")
    async with session_scope() as s:
        ok = set((await s.execute(select(Degree.id).where(Degree.id.in_(body.degree_ids), or_(Degree.campus_id.is_(None), Degree.campus_id == ctx.campus_id)))).scalars())
        await s.execute(text("DELETE FROM campus_degrees WHERE campus_id = :c"), {"c": ctx.campus_id})
        for d in ok:
            s.add(CampusDegree(campus_id=ctx.campus_id, degree_id=d))
    return {"offered": len(ok)}


class DegreeIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    abbreviation: str = Field(min_length=1, max_length=60)
    isced_level: int = Field(ge=3, le=8)
    typical_years: float | None = Field(default=None, gt=0, le=10)
    term_type: Literal["annual", "semester", "trimester", "modular"] = "semester"


@router.post("/staff/degrees", status_code=201)
async def add_degree(body: DegreeIn, ctx: StaffDep) -> dict:
    """A degree the list doesn't have, for this college only."""
    require(ctx, "tpo", "principal")
    async with session_scope() as s:
        d = Degree(id=uuid7(), campus_id=ctx.campus_id, country_code=None, **body.model_dump())
        s.add(d)
        s.add(CampusDegree(campus_id=ctx.campus_id, degree_id=d.id))
    return _deg(d)


class DepartmentIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    native_name: str = Field(default="", max_length=200)


@router.post("/staff/departments", status_code=201)
async def add_department(body: DepartmentIn, ctx: StaffDep) -> dict:
    require(ctx, "tpo", "principal")
    async with session_scope() as s:
        d = Department(id=uuid7(), campus_id=ctx.campus_id, name=body.name.strip(), native_name=body.native_name.strip())
        s.add(d)
        try:
            await s.flush()
        except Exception as exc:
            raise HTTPException(409, "That department already exists") from exc
    return {"id": str(d.id), "name": d.name}


class ProgramIn(BaseModel):
    department_id: uuid.UUID
    degree_id: uuid.UUID
    field_code: str | None = Field(default=None, max_length=10)
    specialisation: str = Field(default="", max_length=200)
    duration_years: float | None = Field(default=None, gt=0, le=10)
    term_type: Literal["annual", "semester", "trimester", "modular"] = "semester"
    intake_per_year: int | None = Field(default=None, ge=0, le=500_000)


@router.post("/staff/programs", status_code=201)
async def add_program(body: ProgramIn, ctx: StaffDep) -> dict:
    """A department running a degree (Computer Engg -> B.E., M.E., Ph.D.): students belong to programmes."""
    require(ctx, "tpo", "principal")
    async with session_scope() as s:
        dept = await s.get(Department, body.department_id)
        if dept is None or dept.campus_id != ctx.campus_id:
            raise HTTPException(404, "No such department")
        offered = (await s.execute(select(CampusDegree).where(CampusDegree.campus_id == ctx.campus_id, CampusDegree.degree_id == body.degree_id))).scalar_one_or_none()
        if offered is None:
            raise HTTPException(422, "Add this degree to the degrees your college offers first")
        if body.field_code and await s.get(FieldRow, body.field_code) is None:
            raise HTTPException(422, "Unknown field code")
        deg = await s.get(Degree, body.degree_id)
        p = Program(id=uuid7(), campus_id=ctx.campus_id, **{**body.model_dump(), "duration_years": body.duration_years or (float(deg.typical_years) if deg.typical_years else None)})
        s.add(p)
    return {"id": str(p.id)}


class BatchIn(BaseModel):
    program_id: uuid.UUID
    admission_year: int = Field(ge=1950, le=2100)
    graduation_year: int | None = Field(default=None, ge=1950, le=2110)
    current_term: int | None = Field(default=None, ge=1, le=20)


@router.post("/staff/batches", status_code=201)
async def add_batch(body: BatchIn, ctx: StaffDep) -> dict:
    require(ctx, "tpo", "principal", "hod")
    async with session_scope() as s:
        p = await s.get(Program, body.program_id)
        if p is None or p.campus_id != ctx.campus_id or (not ctx.whole_campus and p.department_id not in ctx.dept_ids):
            raise HTTPException(404, "No such programme in your scope")
        grad = body.graduation_year or body.admission_year + int(float(p.duration_years or 3))
        if grad < body.admission_year:
            raise HTTPException(422, "Graduation is before admission")
        b = Batch(id=uuid7(), campus_id=ctx.campus_id, program_id=p.id, admission_year=body.admission_year, graduation_year=grad, current_term=body.current_term, term_override=body.current_term is not None)
        s.add(b)
    return {"id": str(b.id), "graduation_year": grad}


# ---- capacity: total -> degree -> department / programme -> batch; children never exceed their parent ----


async def capacity_tree(s, campus_id: uuid.UUID) -> dict:
    alloc = {(a.level, a.ref_id): a.capacity for a in (await s.execute(select(CapacityAllocation).where(CapacityAllocation.campus_id == campus_id))).scalars()}
    used = {(r.level, r.ref_id): r.value for r in (await s.execute(select(CampusRollup).where(CampusRollup.campus_id == campus_id, CampusRollup.metric == "students"))).scalars()}
    progs = (await s.execute(select(Program).where(Program.campus_id == campus_id))).scalars().all()
    bats = (await s.execute(select(Batch).where(Batch.campus_id == campus_id))).scalars().all()

    def node(level, ref):
        cap = alloc.get((level, ref if level != "campus" else campus_id))
        u = used.get((level, "" if level == "campus" else str(ref)), 0)
        return {"level": level, "id": str(ref), "capacity": cap, "used": u, "remaining": None if cap is None else cap - u}

    tree = node("campus", campus_id)
    degrees = sorted({p.degree_id for p in progs}, key=str)
    tree["children"] = []
    for d in degrees:
        dn = node("degree", d)
        dn["children"] = []
        for p in [p for p in progs if p.degree_id == d]:
            pn = node("program", p.id)
            pn["department_id"] = str(p.department_id)
            pn["children"] = [node("batch", b.id) for b in bats if b.program_id == p.id]
            dn["children"].append(pn)
        tree["children"].append(dn)
    tree["departments"] = [node("department", dep) for dep in sorted({p.department_id for p in progs}, key=str)]
    return tree


@router.get("/staff/capacity")
async def get_capacity(ctx: StaffDep) -> dict:
    async with session_scope() as s:
        return await capacity_tree(s, ctx.campus_id)


class CapacityIn(BaseModel):
    level: Literal["campus", "degree", "department", "program", "batch"]
    ref_id: uuid.UUID | None = None
    capacity: int = Field(ge=0, le=4_000_000)


async def check_capacity(s, campus_id: uuid.UUID, level: str, ref: uuid.UUID, value: int) -> None:
    """Raises 422 when the parent would be exceeded or the existing children no longer fit."""
    alloc = {(a.level, a.ref_id): a.capacity for a in (await s.execute(select(CapacityAllocation).where(CapacityAllocation.campus_id == campus_id))).scalars()}
    progs = (await s.execute(select(Program).where(Program.campus_id == campus_id))).scalars().all()
    bats = (await s.execute(select(Batch).where(Batch.campus_id == campus_id))).scalars().all()
    alloc[(level, ref)] = value

    def total(lv, ids):
        return sum(alloc.get((lv, i), 0) for i in ids)

    camp = alloc.get(("campus", campus_id))
    degrees = {p.degree_id for p in progs}
    depts = {p.department_id for p in progs}
    errs = []
    if camp is not None:
        if total("degree", degrees) > camp:
            errs.append(f"Degree totals ({total('degree', degrees):,}) are more than the college total ({camp:,})")
        if total("department", depts) > camp:
            errs.append(f"Department totals ({total('department', depts):,}) are more than the college total ({camp:,})")
    for d in degrees:
        cap = alloc.get(("degree", d))
        kids = [p.id for p in progs if p.degree_id == d]
        if cap is not None and total("program", kids) > cap:
            errs.append(f"Programmes of a degree add up to {total('program', kids):,}, more than the degree's {cap:,}")
    for dep in depts:
        cap = alloc.get(("department", dep))
        kids = [p.id for p in progs if p.department_id == dep]
        if cap is not None and total("program", kids) > cap:
            errs.append(f"Programmes of a department add up to {total('program', kids):,}, more than the department's {cap:,}")
    for p in progs:
        cap = alloc.get(("program", p.id))
        kids = [b.id for b in bats if b.program_id == p.id]
        if cap is not None and total("batch", kids) > cap:
            errs.append(f"Batches of a programme add up to {total('batch', kids):,}, more than the programme's {cap:,}")
    if errs:
        raise HTTPException(422, {"message": "The numbers don't add up", "errors": errs, "helpers": ["split_evenly", "use_intake"]})


@router.put("/staff/capacity")
async def set_capacity(body: CapacityIn, ctx: StaffDep) -> dict:
    require(ctx, "tpo", "principal")
    ref = body.ref_id or ctx.campus_id
    if body.level == "campus":
        ref = ctx.campus_id
    async with session_scope() as s:
        await check_capacity(s, ctx.campus_id, body.level, ref, body.capacity)
        a = (await s.execute(select(CapacityAllocation).where(CapacityAllocation.campus_id == ctx.campus_id, CapacityAllocation.level == body.level, CapacityAllocation.ref_id == ref))).scalar_one_or_none()
        if a is None:
            s.add(CapacityAllocation(id=uuid7(), campus_id=ctx.campus_id, level=body.level, ref_id=ref, capacity=body.capacity, updated_by=ctx.user_id))
        else:
            a.capacity, a.updated_by = body.capacity, ctx.user_id
        if body.level == "campus":
            (await s.get(Campus, ctx.campus_id)).total_capacity = body.capacity
    await audit(ctx, "capacity", level=body.level, ref=str(ref), capacity=body.capacity)
    return {"ok": True}


@router.post("/staff/capacity/split")
async def split_capacity(level: Literal["degree", "program", "batch"], mode: Literal["even", "intake"], parent_id: uuid.UUID | None, ctx: StaffDep) -> dict:
    """Helpers: split a parent's capacity evenly across its children, or by each programme's yearly intake."""
    require(ctx, "tpo", "principal")
    async with session_scope() as s:
        alloc = {(a.level, a.ref_id): a for a in (await s.execute(select(CapacityAllocation).where(CapacityAllocation.campus_id == ctx.campus_id))).scalars()}
        progs = (await s.execute(select(Program).where(Program.campus_id == ctx.campus_id))).scalars().all()
        if level == "degree":
            parent, kids = alloc.get(("campus", ctx.campus_id)), [(d, None) for d in sorted({p.degree_id for p in progs}, key=str)]
        elif level == "program":
            parent, kids = alloc.get(("degree", parent_id)), [(p.id, p) for p in progs if p.degree_id == parent_id]
        else:
            parent = alloc.get(("program", parent_id))
            kids = [(b.id, None) for b in (await s.execute(select(Batch).where(Batch.campus_id == ctx.campus_id, Batch.program_id == parent_id))).scalars()]
        if parent is None or not kids:
            raise HTTPException(409, "Set the parent's capacity first")
        if mode == "intake" and level == "program":
            weights = [float(p.intake_per_year or 0) * float(p.duration_years or 1) for _, p in kids]
        else:
            weights = [1.0] * len(kids)
        tot = sum(weights) or len(kids)
        shares = [int(parent.capacity * w / tot) for w in weights]
        for (kid, _), share in zip(kids, shares, strict=True):
            a = alloc.get((level, kid))
            if a is None:
                s.add(CapacityAllocation(id=uuid7(), campus_id=ctx.campus_id, level=level, ref_id=kid, capacity=share, updated_by=ctx.user_id))
            else:
                a.capacity, a.updated_by = share, ctx.user_id
    await audit(ctx, "capacity_split", level=level, mode=mode)
    return {"children": len(kids)}


# =============================== students (college records; JobPilot data with consent) ===============================


def _cursor(created_at: datetime, rid: uuid.UUID) -> str:
    """An opaque, URL-safe keyset cursor: (created_at, id) of the last row."""
    import base64

    return base64.urlsafe_b64encode(f"{created_at.isoformat()}|{rid}".encode()).decode().rstrip("=")


def _parse_cursor(c: str | None):
    import base64

    if not c:
        return None
    try:
        ts, rid = base64.urlsafe_b64decode(c + "=" * (-len(c) % 4)).decode().split("|")
        return datetime.fromisoformat(ts), uuid.UUID(rid)
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(422, "Bad cursor") from exc


@router.get("/staff/students")
async def list_students(ctx: StaffDep, department_id: uuid.UUID | None = None, program_id: uuid.UUID | None = None, batch_id: uuid.UUID | None = None,
                        q: str = "", cursor: str | None = None, limit: int = 50) -> dict:
    """Keyset-paginated college records in the viewer's scope (row-level security decides which rows exist)."""
    limit = max(1, min(limit, 100))
    async with staff_session(ctx) as s:
        stmt = select(RosterStudent).where(RosterStudent.campus_id == ctx.campus_id)
        for col, v in ((RosterStudent.department_id, department_id), (RosterStudent.program_id, program_id), (RosterStudent.batch_id, batch_id)):
            if v:
                stmt = stmt.where(col == v)
        if q.strip():
            term = q.strip().lower()[:60]
            stmt = stmt.where(or_(RosterStudent.search_name.like(f"%{term}%"), RosterStudent.student_id_at_institution == q.strip()))
        cur = _parse_cursor(cursor)
        if cur:
            stmt = stmt.where(func.row(RosterStudent.created_at, RosterStudent.id) < func.row(cur[0], cur[1]))
        rows = (await s.execute(stmt.order_by(RosterStudent.created_at.desc(), RosterStudent.id.desc()).limit(limit + 1))).scalars().all()
        sharing = set()
        claimed = [r.claimed_user_id for r in rows if r.claimed_user_id]
        if claimed:  # memberships are visible only for students who share (or are waiting for confirmation)
            sharing = set((await s.execute(select(CampusMembership.user_id).where(CampusMembership.campus_id == ctx.campus_id, CampusMembership.user_id.in_(claimed), CampusMembership.shares_with_college))).scalars())
    more = len(rows) > limit
    rows = rows[:limit]
    return {
        "items": [_record(r, r.claimed_user_id in sharing) for r in rows],
        "next_cursor": _cursor(rows[-1].created_at, rows[-1].id) if more else None,
    }


def _record(r: RosterStudent, shares: bool) -> dict:
    return {"id": str(r.id), "student_id": r.student_id_at_institution, "name": r.name, "department_id": str(r.department_id) if r.department_id else None,
            "program_id": str(r.program_id) if r.program_id else None, "batch_id": str(r.batch_id) if r.batch_id else None,
            "score": float(r.score_value) if r.score_value is not None else None, "score_scale": r.score_scale, "pending_subjects": r.pending_subjects,
            "graduation_year": r.graduation_year, "current_term": r.current_term, "custom": r.custom, "source": r.source,
            "self_reported_academics": r.source == "student_legacy", "shares_with_college": shares}


@router.get("/staff/students/{roster_id}")
async def student_detail(roster_id: str, ctx: StaffDep) -> dict:
    """One student: the college record; their JobPilot data (achievements, proof) only if they share it. Logged."""
    from app.campus.storage import signed_url

    async with staff_session(ctx) as s:
        r = (await s.execute(select(RosterStudent).where(RosterStudent.campus_id == ctx.campus_id, RosterStudent.id == _uuid(roster_id)))).scalar_one_or_none()
        if r is None:
            raise HTTPException(404, "No such student in your scope")
        achievements = []
        shares = False
        if r.claimed_user_id:
            shares = bool((await s.execute(select(CampusMembership.id).where(CampusMembership.campus_id == ctx.campus_id, CampusMembership.user_id == r.claimed_user_id, CampusMembership.shares_with_college))).first())
            achievements = (await s.execute(select(StudentAchievement).where(StudentAchievement.campus_id == ctx.campus_id, StudentAchievement.user_id == r.claimed_user_id).order_by(StudentAchievement.start_date.desc().nulls_last()))).scalars().all()
    await audit(ctx, "view_student", r.claimed_user_id, roster_id=roster_id)
    return {
        "record": _record(r, shares),
        "achievements": [_achievement(a, staff=True, url=signed_url(ctx.campus_id, a.proof_file_id, ctx.user_id) if a.proof_file_id else None) for a in achievements],
        "note": None if shares or not r.claimed_user_id else "This student hasn't chosen to share their JobPilot activity with the college: only the college's own record is shown.",
    }


def _achievement(a: StudentAchievement, staff: bool = False, url: str | None = None) -> dict:
    d = {"id": str(a.id), "campus_id": str(a.campus_id), "kind": a.kind, "sub_type": a.sub_type, "category": a.category, "title": a.title, "organisation": a.organisation,
         "level": a.level, "position": a.position, "mode": a.mode, "start_date": a.start_date.isoformat() if a.start_date else None,
         "end_date": a.end_date.isoformat() if a.end_date else None, "ongoing": a.ongoing, "description": a.description, "link": a.link,
         "status": a.status, "label": {"self_reported": "Self-reported", "verified": "Verified", "rejected": "Rejected"}[a.status], "reject_reason": a.reject_reason,
         "verifier_flags": a.verifier_flags, "proof_url": url, "has_proof": bool(a.proof_file_id), "show_on_proof_page": a.show_on_proof_page,
         "stipend_inr": a.stipend_inr if (not staff or not a.stipend_private) else None, "stipend_private": a.stipend_private,
         "department_id": str(a.department_id) if a.department_id else None, "created_at": a.created_at.isoformat() if a.created_at else None}
    return d


class ConfirmIn(BaseModel):
    approve: bool = True


@router.post("/staff/students/memberships/{membership_id}")
async def confirm_student(membership_id: str, body: ConfirmIn, ctx: StaffDep) -> dict:
    """A student who picked a programme themselves stays pending until staff of that programme confirm it."""
    from app.api.routes.campus_profile import place_or_waitlist

    async with staff_session(ctx) as s:
        m = (await s.execute(select(CampusMembership).where(CampusMembership.campus_id == ctx.campus_id, CampusMembership.id == _uuid(membership_id), CampusMembership.kind == "student"))).scalar_one_or_none()
        if m is None or m.status not in ("pending", "waitlisted"):
            raise HTTPException(404, "No such request in your scope")
        uid = m.user_id
    async with session_scope() as s:
        m = (await s.execute(select(CampusMembership).where(CampusMembership.campus_id == ctx.campus_id, CampusMembership.id == _uuid(membership_id)))).scalar_one()
        if body.approve:
            m.status = await place_or_waitlist(s, m)
            if m.status == "active":
                await sync_legacy(s, ctx.campus_id, m.user_id, "student")
        else:
            m.status = "deactivated"
        status = m.status
    await audit(ctx, "student_confirm" if body.approve else "student_decline", uid)
    return {"status": status}


@router.get("/staff/students-pending")
async def pending_students(ctx: StaffDep) -> list[dict]:
    async with staff_session(ctx) as s:
        rows = (
            await s.execute(
                select(CampusMembership, User).join(User, User.id == CampusMembership.user_id)
                .where(CampusMembership.campus_id == ctx.campus_id, CampusMembership.kind == "student", CampusMembership.status.in_(["pending", "waitlisted"]))
                .order_by(CampusMembership.created_at).limit(200)
            )
        ).all()
    return [{"membership_id": str(m.id), "name": u.name or "Student", "status": m.status, "department_id": str(m.department_id) if m.department_id else None,
             "program_id": str(m.program_id) if m.program_id else None, "batch_id": str(m.batch_id) if m.batch_id else None} for m, u in rows]


# =============================== verification queue ===============================


@router.get("/staff/achievements")
async def achievement_queue(ctx: StaffDep, status: str = "self_reported", kind: str | None = None, level: str | None = None,
                            department_id: uuid.UUID | None = None, cursor: str | None = None, limit: int = 50) -> dict:
    limit = max(1, min(limit, 100))
    async with staff_session(ctx) as s:
        stmt = select(StudentAchievement).where(StudentAchievement.campus_id == ctx.campus_id, StudentAchievement.status == status)
        if kind:
            stmt = stmt.where(StudentAchievement.kind == kind)
        if level:
            stmt = stmt.where(StudentAchievement.level == level)
        if department_id:
            stmt = stmt.where(StudentAchievement.department_id == department_id)
        cur = _parse_cursor(cursor)
        if cur:
            stmt = stmt.where(func.row(StudentAchievement.created_at, StudentAchievement.id) < func.row(cur[0], cur[1]))
        rows = (await s.execute(stmt.order_by(StudentAchievement.created_at.desc(), StudentAchievement.id.desc()).limit(limit + 1))).scalars().all()
        names = {}
        uids = [a.user_id for a in rows]
        if uids:
            names = dict((await s.execute(select(RosterStudent.claimed_user_id, RosterStudent.name).where(RosterStudent.campus_id == ctx.campus_id, RosterStudent.claimed_user_id.in_(uids)))).all())
    more = len(rows) > limit
    rows = rows[:limit]
    from app.campus.storage import signed_url

    return {"items": [{**_achievement(a, staff=True, url=signed_url(ctx.campus_id, a.proof_file_id, ctx.user_id) if a.proof_file_id else None), "student": names.get(a.user_id, "Student")} for a in rows],
            "next_cursor": _cursor(rows[-1].created_at, rows[-1].id) if more else None}


class VerifyIn(BaseModel):
    decision: Literal["verified", "rejected"]
    reason: str = Field(default="", max_length=300)


async def _verify(ctx, ids: list[uuid.UUID], body: VerifyIn) -> int:
    if body.decision == "rejected" and len(body.reason.strip()) < 3:
        raise HTTPException(422, "Say why it's rejected: the student sees the reason")
    async with staff_session(ctx) as s:  # row-level security: only entries this staff member may verify are touched
        res = await s.execute(
            update(StudentAchievement)
            .where(StudentAchievement.campus_id == ctx.campus_id, StudentAchievement.id.in_(ids))
            .values(status=body.decision, reject_reason=body.reason.strip()[:300] if body.decision == "rejected" else None, verified_by=ctx.user_id, verified_at=datetime.now(UTC))
            .execution_options(synchronize_session=False)
        )
        return res.rowcount or 0


@router.post("/staff/achievements/{achievement_id}/verify")
async def verify_achievement(achievement_id: str, body: VerifyIn, ctx: StaffDep) -> dict:
    n = await _verify(ctx, [_uuid(achievement_id)], body)
    if not n:
        raise HTTPException(404, "No such entry in your department (or the student doesn't share it)")
    await audit(ctx, "verify", None, achievement_id=achievement_id, decision=body.decision)
    return {"ok": True}


class BulkVerify(VerifyIn):
    ids: list[uuid.UUID] = Field(min_length=1, max_length=200)
    confirm: bool = False


@router.post("/staff/achievements/bulk")
async def bulk_verify(body: BulkVerify, ctx: StaffDep) -> dict:
    if not body.confirm:
        raise HTTPException(422, f"Confirm the {body.decision} decision for {len(body.ids)} entries")
    n = await _verify(ctx, body.ids, body)
    await audit(ctx, "verify_bulk", None, count=n, decision=body.decision)
    return {"updated": n}


# =============================== roster import, jobs ===============================


@router.post("/staff/roster/import", status_code=202)
async def roster_import(ctx: StaffDep, file: UploadFile = File(...)) -> dict:
    """CSV or Excel: student id, name, department, degree, admission/graduation year, term, score, pending subjects,
    college email, plus your custom fields. Rows become college records and invites (never accounts). Up to 1 lakh+
    rows; parsed and upserted in batches of 5,000 by a background job."""
    require(ctx, "tpo", "principal", "hod")
    await hit("campus_job", str(ctx.campus_id))
    name = (file.filename or "roster.csv").lower()
    if not name.endswith((".csv", ".xlsx")):
        raise HTTPException(415, "Upload a .csv or .xlsx file")
    data = await file.read(60 * 1024 * 1024 + 1)
    if len(data) > 60 * 1024 * 1024:
        raise HTTPException(413, "Up to 60 MB per file")
    from app.campus.storage import encrypt, sha256

    job = await cjobs.enqueue(ctx.campus_id, "roster_import", f"roster:{ctx.campus_id}:{sha256(data)}", {"filename": name}, encrypt(data), ctx.user_id)
    await audit(ctx, "roster_import", None, job_id=str(job), filename=name, bytes=len(data))
    return {"job_id": str(job)}


@router.get("/staff/jobs/{job_id}")
async def job_status(job_id: str, ctx: StaffDep) -> dict:
    async with session_scope() as s:
        j = await s.get(CampusJob, _uuid(job_id))
        if j is None or j.campus_id != ctx.campus_id:
            raise HTTPException(404, "No such job")
    res = dict(j.result or {})
    errs = res.pop("errors", [])
    return {"id": str(j.id), "kind": j.kind, "status": j.status, "progress": j.progress, "total": j.total, "result": res, "error_count": len(errs), "error": j.error}


@router.get("/staff/jobs/{job_id}/errors.csv")
async def job_errors(job_id: str, ctx: StaffDep) -> Response:
    async with session_scope() as s:
        j = await s.get(CampusJob, _uuid(job_id))
        if j is None or j.campus_id != ctx.campus_id:
            raise HTTPException(404, "No such job")
    return Response(cjobs.errors_csv(j), media_type="text/csv", headers={"content-disposition": "attachment; filename=roster-errors.csv"})


# =============================== drives with rules as data ===============================


class RoundIn(BaseModel):
    name: str = Field(max_length=120)
    type: str = Field(max_length=40)
    date: str | None = None


class DriveIn(BaseModel):
    company: str = Field(min_length=2, max_length=200)
    role: str = Field(min_length=2, max_length=200)
    kind: Literal["internship", "full_time", "apprenticeship", "fellowship"] = "full_time"
    compensation: str = Field(default="", max_length=100)
    register_by: datetime | None = None
    rounds: list[RoundIn] = Field(default_factory=list, max_length=15)
    rules: list[dict] = Field(default_factory=list, max_length=30)
    notes: str = Field(default="", max_length=4000)


@router.post("/staff/drives", status_code=201)
async def create_drive(body: DriveIn, ctx: StaffDep) -> dict:
    require(ctx, "tpo", "principal", "coordinator", "hod")
    try:
        rules = validate(body.rules)
    except RuleError as exc:
        raise HTTPException(422, str(exc)) from exc
    async with session_scope() as s:
        d = CampusDrive(org_id=ctx.campus_id, company=body.company, role=body.role, kind=body.kind, compensation=body.compensation, register_by=body.register_by,
                        rounds=[r.model_dump() for r in body.rounds], eligibility={"v": 2, "rules": rules}, notes=body.notes)
        s.add(d)
        await s.flush()
        drive_id = d.id
    job = await cjobs.enqueue(ctx.campus_id, "eligibility", f"elig:{drive_id}:{datetime.now(UTC):%Y%m%d%H%M%S}", {"drive_id": str(drive_id)}, by=ctx.user_id)
    await audit(ctx, "drive_create", None, drive_id=str(drive_id), rule_ids=[r["id"] for r in rules])
    return {"id": str(drive_id), "eligibility_job": str(job)}


@router.post("/staff/drives/{drive_id}/evaluate", status_code=202)
async def evaluate_drive(drive_id: str, ctx: StaffDep) -> dict:
    async with session_scope() as s:
        d = await s.get(CampusDrive, _uuid(drive_id))
        if d is None or d.org_id != ctx.campus_id:
            raise HTTPException(404, "No such drive")
    job = await cjobs.enqueue(ctx.campus_id, "eligibility", f"elig:{drive_id}:{datetime.now(UTC):%Y%m%d%H%M}", {"drive_id": drive_id}, by=ctx.user_id)
    return {"job_id": str(job)}


@router.get("/staff/drives")
async def list_drives(ctx: StaffDep) -> list[dict]:
    async with staff_session(ctx) as s:
        drives = (await s.execute(select(CampusDrive).where(CampusDrive.org_id == ctx.campus_id).order_by(CampusDrive.created_at.desc()).limit(100))).scalars().all()
        counts = dict(
            (await s.execute(text("SELECT drive_id, count(*) FILTER (WHERE eligible) FROM drive_eligibility WHERE campus_id = :c GROUP BY drive_id"), {"c": ctx.campus_id})).all()
        )
    return [{"id": str(d.id), "company": d.company, "role": d.role, "kind": d.kind, "compensation": d.compensation, "register_by": d.register_by.isoformat() if d.register_by else None,
             "rounds": d.rounds, "rules": (d.eligibility or {}).get("rules", []), "eligible_in_scope": int(counts.get(d.id, 0))} for d in drives]


@router.get("/staff/round-templates")
async def round_templates(ctx: StaffDep, field_code: str | None = None, role: str = "") -> dict:
    """Round types for any field, and the defaults for this field (a coding test only where the role needs one)."""
    import re as _re

    from app.campus.rounds import ROUND_TYPES, defaults_for

    needs_code = bool(_re.search(r"(?i)\b(software|developer|engineer.*(software|data|ml)|data scien|programmer|sde|backend|frontend|full.?stack)\b", role))
    return {"types": ROUND_TYPES, "defaults": defaults_for(field_code, needs_code)}


# =============================== dashboard with drill-down ===============================


@router.get("/staff/dashboard")
async def dashboard(ctx: StaffDep, level: Literal["campus", "degree", "department", "program", "batch"] = "campus", ref_id: str = "") -> dict:
    """Pre-aggregated numbers for one node and its children (college -> degree -> programme -> batch; departments too).
    HODs and faculty start at their own scope."""
    async with session_scope() as s:
        if not ctx.whole_campus and level == "campus":  # HODs and faculty start at their own scope
            level, ref_id = (("department", str(ctx.dept_ids[0])) if ctx.dept_ids else ("program", str(ctx.program_ids[0])) if ctx.program_ids
                             else ("batch", str(ctx.batch_ids[0])) if ctx.batch_ids else ("department", ""))
        rows = (await s.execute(select(CampusRollup).where(CampusRollup.campus_id == ctx.campus_id))).scalars().all()
        progs = (await s.execute(select(Program, Degree).join(Degree, Degree.id == Program.degree_id).where(Program.campus_id == ctx.campus_id))).all()
        depts = {str(d.id): d.name for d in (await s.execute(select(Department).where(Department.campus_id == ctx.campus_id))).scalars()}
        bats = (await s.execute(select(Batch).where(Batch.campus_id == ctx.campus_id))).scalars().all()
    metrics: dict = {}
    updated = None
    for r in rows:
        metrics.setdefault((r.level, r.ref_id), {})[r.metric] = r.value
        updated = max(updated, r.updated_at) if updated else r.updated_at
    key = (level, "" if level == "campus" else ref_id)
    if level == "campus":
        children = [("degree", str(d.id), d.abbreviation) for d in {d.id: d for _, d in progs}.values()]
        children += [("department", k, v) for k, v in depts.items()]
    elif level == "degree":
        children = [("program", str(p.id), f"{d.abbreviation} {p.specialisation}".strip() + f" · {depts.get(str(p.department_id), '')}") for p, d in progs if str(d.id) == ref_id]
    elif level == "department":
        children = [("program", str(p.id), f"{d.abbreviation} {p.specialisation}".strip()) for p, d in progs if str(p.department_id) == ref_id]
    elif level == "program":
        children = [("batch", str(b.id), f"{b.admission_year}–{b.graduation_year}") for b in bats if str(b.program_id) == ref_id]
    else:
        children = []
    if not ctx.whole_campus:
        scope_d, scope_p, scope_b = {str(d) for d in ctx.dept_ids}, {str(p) for p in ctx.program_ids}, {str(b) for b in ctx.batch_ids}
        prog_dept = {str(p.id): str(p.department_id) for p, _ in progs}
        bat_prog = {str(b.id): str(b.program_id) for b in bats}

        def visible(lv, rid):
            if lv == "department":
                return rid in scope_d
            if lv == "program":
                return rid in scope_p or prog_dept.get(rid) in scope_d
            if lv == "batch":
                return rid in scope_b or bat_prog.get(rid) in scope_p or prog_dept.get(bat_prog.get(rid, "")) in scope_d
            return False

        if not visible(level, ref_id):
            raise HTTPException(403, "That part of the college is outside your scope")
        children = [c for c in children if visible(c[0], c[1])]
    # Totals only (no individual's data): not audit-logged, unlike student views, approvals and exports.
    return {"level": level, "ref_id": ref_id, "metrics": metrics.get(key, {}), "updated_at": updated.isoformat() if updated else None,
            "children": [{"level": lv, "ref_id": rid, "name": name, "metrics": metrics.get((lv, rid), {})} for lv, rid, name in children]}


@router.post("/staff/rollups/refresh", status_code=202)
async def refresh_rollups(ctx: StaffDep) -> dict:
    job = await cjobs.enqueue(ctx.campus_id, "rollup", f"rollup:{ctx.campus_id}:{datetime.now(UTC):%Y%m%d%H%M}")
    return {"job_id": str(job)}


# =============================== export (scope only, logged) ===============================


@router.get("/staff/export.csv")
async def export_csv(ctx: StaffDep, department_id: uuid.UUID | None = None, program_id: uuid.UUID | None = None, batch_id: uuid.UUID | None = None) -> StreamingResponse:
    campus = await _campus(ctx.campus_id)
    count = {"n": 0}

    async def rows():
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow([campus.student_id_label, "Name", "Department", "Programme", "Batch", "Score", "Scale", campus.pending_subjects_label or "Pending subjects", "Graduation year", "Academics from"])
        yield buf.getvalue()
        last = None
        while True:
            async with staff_session(ctx) as s:
                stmt = select(RosterStudent).where(RosterStudent.campus_id == ctx.campus_id)
                for col, v in ((RosterStudent.department_id, department_id), (RosterStudent.program_id, program_id), (RosterStudent.batch_id, batch_id)):
                    if v:
                        stmt = stmt.where(col == v)
                if last:
                    stmt = stmt.where(RosterStudent.id > last)
                batch = (await s.execute(stmt.order_by(RosterStudent.id).limit(2000))).scalars().all()
            if not batch:
                break
            buf = io.StringIO()
            w = csv.writer(buf)
            for r in batch:
                w.writerow([r.student_id_at_institution, r.name, r.department_id or "", r.program_id or "", r.batch_id or "", r.score_value if r.score_value is not None else "",
                            json.dumps(r.score_scale) if r.score_scale else "", r.pending_subjects if r.pending_subjects is not None else "", r.graduation_year or "",
                            "student (self-reported)" if r.source == "student_legacy" else "college"])
            count["n"] += len(batch)
            last = batch[-1].id
            yield buf.getvalue()
        await audit(ctx, "export", None, rows=count["n"], department_id=str(department_id) if department_id else None, program_id=str(program_id) if program_id else None)

    return StreamingResponse(rows(), media_type="text/csv", headers={"content-disposition": "attachment; filename=students.csv"})


@router.get("/staff/audit")
async def audit_log(ctx: StaffDep, limit: int = 100) -> list[dict]:
    require(ctx, "tpo", "principal")
    async with staff_session(ctx) as s:
        rows = (await s.execute(text("SELECT at, actor_user_id, action, subject_user_id, detail FROM staff_view_audit_log WHERE campus_id = :c ORDER BY at DESC LIMIT :n"), {"c": ctx.campus_id, "n": min(limit, 500)})).all()
    return [{"at": r.at.isoformat(), "actor": str(r.actor_user_id) if r.actor_user_id else None, "action": r.action, "subject": str(r.subject_user_id) if r.subject_user_id else None, "detail": r.detail} for r in rows]


# =============================== proof files (signed links) ===============================


@router.get("/files/{campus_id}/{file_id}")
async def proof_file(campus_id: str, file_id: str, exp: int, sig: str, user: UserDep, request: Request) -> Response:
    """A proof file, through a 10-minute signed link issued to this viewer, and only if row-level security lets the
    viewer see it right now (its owner, or staff in scope while the student shares)."""
    from app.campus.access import campus_session, read_staff_token, staff_ctx
    from app.campus.models import ProofFile
    from app.campus.storage import check_signature, decrypt

    cid, fid = _uuid(campus_id), _uuid(file_id)
    if not check_signature(cid, fid, exp, sig, user.id):
        raise HTTPException(403, "This link has expired")
    token = request.headers.get("x-staff-token") or request.cookies.get("jp_staff")
    claims = read_staff_token(token) if token else None
    if claims and claims.get("campus_id") == str(cid):
        ctx = await staff_ctx(request, user)
        sess = staff_session(ctx)
    else:
        sess = campus_session("student", user.id, [])
    async with sess as s:
        f = (await s.execute(select(ProofFile).where(ProofFile.campus_id == cid, ProofFile.id == fid))).scalar_one_or_none()
        if f is None:
            raise HTTPException(404, "Not found")
        data = decrypt(f.data_enc) if f.data_enc else b""
    return Response(data, media_type=f.mime, headers={"cache-control": "private, max-age=60", "x-content-type-options": "nosniff", "content-disposition": "inline"})


# =============================== JobPilot admin: create a campus, appoint the first TPO ===============================


class CampusCreate(BaseModel):
    aishe_id: str | None = Field(default=None, max_length=20)
    name: str | None = Field(default=None, max_length=300)
    city: str = Field(default="", max_length=120)
    state: str = Field(default="", max_length=120)
    country_code: str = Field(default="IN", min_length=2, max_length=2)
    website: str | None = Field(default=None, max_length=200)
    allowed_email_domains: list[str] = Field(default_factory=list, max_length=10)
    institution_id: uuid.UUID | None = None  # a campus of an existing university group


admin = APIRouter(prefix="/admin/campuses", tags=["admin"])


@admin.post("", status_code=201)
async def create_campus(body: CampusCreate, _: AdminDep) -> dict:
    from app.models import RefInstitution

    async with session_scope() as s:
        ref = await s.get(RefInstitution, body.aishe_id) if body.aishe_id else None
        name = (ref.name if ref else body.name or "").strip()
        if not name:
            raise HTTPException(422, "Pick the college from the AISHE list or give its name")
        inst_id = body.institution_id
        if inst_id is None:
            inst = Institution(id=uuid7(), name=ref.university if ref and ref.university else name, type="standalone" if not (ref and ref.university) else "college_group",
                               country_code=body.country_code.upper())
            s.add(inst)
            await s.flush()
            inst_id = inst.id
        domains = [d.strip().lower().lstrip("@") for d in body.allowed_email_domains if d.strip() and d.strip().lower().lstrip("@") not in otp.PERSONAL_DOMAINS]
        c = Campus(id=uuid7(), institution_id=inst_id, name=name, city=body.city or (ref.district if ref else ""), state=body.state or (ref.state if ref else ""),
                   country_code=body.country_code.upper(), aishe_id=ref.aishe_id if ref else None, website=body.website, allowed_email_domains=domains,
                   status="active" if ref else "review")
        s.add(c)
        await s.flush()
        import secrets

        s.add(Organization(id=c.id, name=name, slug=f"c-{c.id.hex[-12:]}", invite_code=secrets.token_hex(4).upper()))
    return {"id": str(c.id), "name": name, "status": c.status, "aishe_match": bool(ref)}


class TpoIn(BaseModel):
    email: EmailStr
    role: Literal["tpo", "principal", "university_admin"] = "tpo"


@admin.post("/{campus_id}/staff")
async def appoint(campus_id: str, body: TpoIn, _: AdminDep) -> dict:
    """TPO / Principal access is granted only by JobPilot (here) or by an existing TPO."""
    async with session_scope() as s:
        c = await s.get(Campus, _uuid(campus_id))
        u = (await s.execute(select(User).where(func.lower(User.email) == str(body.email).lower()))).scalar_one_or_none()
        if c is None or u is None:
            raise HTTPException(404, "No such campus or account")
        m = (await s.execute(select(CampusMembership).where(CampusMembership.campus_id == c.id, CampusMembership.user_id == u.id, CampusMembership.kind == "staff"))).scalar_one_or_none()
        if m is None:
            m = CampusMembership(campus_id=c.id, id=uuid7(), institution_id=c.institution_id, user_id=u.id, kind="staff")
            s.add(m)
        m.role, m.status, m.email_verified = body.role, "active", True
        await sync_legacy(s, c.id, u.id, body.role)
    return {"ok": True}


@admin.get("/aishe")
async def aishe_search(_: AdminDep, q: str) -> list[dict]:
    return await search_institutions(q)


async def search_institutions(q: str, limit: int = 20) -> list[dict]:
    term = q.strip().lower()[:80]
    if len(term) < 3:
        return []
    async with session_scope() as s:
        rows = (await s.execute(text("SELECT aishe_id, name, kind, state, district, university FROM ref_institutions WHERE lower(name) LIKE :q ORDER BY length(name) LIMIT :n"),
                                {"q": f"%{term}%", "n": limit})).all()
    return [dict(r._mapping) for r in rows]


@router.get("/institutions/search")
async def institution_search(user: UserDep, q: str) -> list[dict]:
    """The AISHE 2015-16 directory, for the setup wizard ('add my college' when it's missing)."""
    await hit("resume_tools", str(user.id))
    return await search_institutions(q)

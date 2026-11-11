"""Placement-cell portal: staff joining with the college's staff code, roles and department scope, the student
pipeline (AI match proposals staff approve, then rounds to placed), college-only jobs, precision of the AI's
proposals, the student's own pipeline view, and campus pricing enquiries.

Every staff read of student-level data runs inside campus_v2.officer_scope (Postgres row-level security: only
students who share their progress) and is written to the audit log."""

import uuid
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select

from app.api.deps import RealUserDep, SessionDep, UserDep
from app.models import AuditEvent, CampusLead, CampusPlacement, Job, JobMatch, Organization, OrgMember, Profile, User
from app.services import placement as pc
from app.services.campus_v2 import officer_scope
from app.services.ratelimit import client_ip, hit

router = APIRouter(tags=["placement-cell"])


async def staff_member(user: UserDep, session: SessionDep) -> OrgMember:
    m = (await session.execute(select(OrgMember).where(OrgMember.user_id == user.id, OrgMember.role.in_([*pc.STAFF_ROLES, "officer"])))).scalar_one_or_none()
    if m is None:
        raise HTTPException(403, "For college placement staff only")
    return m


StaffDep = Annotated[OrgMember, Depends(staff_member)]


def need(member: OrgMember, perm: str) -> None:
    if not pc.can(member, perm):
        raise HTTPException(403, f"Your role ({pc.ROLE_LABEL[pc.role_of(member)]}) can't do that")


# ---------- staff ----------


class StaffJoin(BaseModel):
    code: str = Field(min_length=6, max_length=40)
    role: Literal["hod", "teacher"]
    department: str = Field(default="", max_length=120)


@router.post("/college/staff/join")
async def join_as_staff(body: StaffJoin, user: RealUserDep, session: SessionDep) -> dict:
    """HODs and teachers join their college with its staff code (and, if the college requires it, an email on its
    domain). TPOs are appointed by JobPilot or promoted by another TPO, never self-selected."""
    await hit("staff_join", str(user.id))
    org = await pc.org_for_staff_code(session, body.code)
    if org is None:
        raise HTTPException(404, "That staff code doesn't match a college. Ask your placement officer for the current one.")
    if not pc.email_allowed(org, user.email):
        raise HTTPException(403, f"Use your {org.domain} email to join {org.name} as staff.")
    existing = (await session.execute(select(OrgMember).where(OrgMember.user_id == user.id))).scalar_one_or_none()
    if existing:
        raise HTTPException(409, "This account already belongs to a college. Leave it first, or use a separate staff account.")
    if body.role == "hod" and not body.department.strip():
        raise HTTPException(422, "Heads of department: add your department")
    m = OrgMember(org_id=org.id, user_id=user.id, role=body.role, department=body.department.strip())
    session.add(m)
    session.add(AuditEvent(actor_user_id=user.id, action="staff_join", subject=str(org.id), detail={"role": body.role, "department": m.department}))
    await pc.publish_staff(session, org.id, "campus_update", staff=True)
    await session.commit()
    return {"college": org.name, "role": body.role, "label": pc.ROLE_LABEL[body.role], "department": m.department}


@router.get("/college/me")
async def me(member: StaffDep, session: SessionDep) -> dict:
    org = await session.get(Organization, member.org_id)
    role = pc.role_of(member)
    return {
        "college": org.name,
        "role": role,
        "label": pc.ROLE_LABEL[role],
        "department": member.department,
        "permissions": sorted(pc.PERMS[role]),
        "domain": org.domain,
        "staff_code_set": bool(org.staff_code_hash),
        "staff_code_set_at": org.staff_code_set_at.isoformat() if org.staff_code_set_at else None,
    }


@router.get("/college/staff")
async def list_staff(member: StaffDep, session: SessionDep) -> list[dict]:
    rows = (await session.execute(select(OrgMember, User).join(User, User.id == OrgMember.user_id).where(OrgMember.org_id == member.org_id, OrgMember.role.in_([*pc.STAFF_ROLES, "officer"])))).all()
    return [{"id": str(m.id), "name": u.name or u.email.split("@")[0], "email": u.email, "role": pc.role_of(m), "label": pc.ROLE_LABEL[pc.role_of(m)], "department": m.department, "you": m.id == member.id} for m, u in rows]


class StaffUpdate(BaseModel):
    role: Literal["tpo", "hod", "teacher"]
    department: str = Field(default="", max_length=120)


@router.put("/college/staff/{member_id}")
async def update_staff(member_id: uuid.UUID, body: StaffUpdate, member: StaffDep, session: SessionDep) -> dict:
    need(member, "manage_staff")
    m = await session.get(OrgMember, member_id)
    if m is None or m.org_id != member.org_id or m.role == "student":
        raise HTTPException(404, "No such staff member")
    m.role, m.department = body.role, body.department.strip()
    session.add(AuditEvent(actor_user_id=member.user_id, action="staff_role", subject=str(m.user_id), detail={"role": body.role, "department": m.department}))
    await session.commit()
    return {"ok": True}


@router.delete("/college/staff/{member_id}", status_code=204)
async def remove_staff(member_id: uuid.UUID, member: StaffDep, session: SessionDep) -> None:
    need(member, "manage_staff")
    m = await session.get(OrgMember, member_id)
    if m is None or m.org_id != member.org_id or m.role == "student":
        raise HTTPException(404, "No such staff member")
    if m.id == member.id:
        raise HTTPException(409, "You can't remove yourself")
    await session.delete(m)
    session.add(AuditEvent(actor_user_id=member.user_id, action="staff_remove", subject=str(m.user_id), detail={}))
    await session.commit()


@router.post("/college/staff-code")
async def rotate_staff_code(member: StaffDep, session: SessionDep) -> dict:
    """A new staff code (the old one stops working). Shown once: only its hash is stored."""
    need(member, "manage_staff")
    org = await session.get(Organization, member.org_id)
    code = pc.new_staff_code()
    org.staff_code_hash, org.staff_code_set_at = pc.hash_code(code), datetime.now(UTC)
    session.add(AuditEvent(actor_user_id=member.user_id, action="staff_code_rotate", subject=str(org.id), detail={}))
    await session.commit()
    return {"code": code, "note": "Copy it now: it won't be shown again. Share it only with staff."}


class CollegeSettings(BaseModel):
    domain: str | None = Field(default=None, max_length=120, pattern=r"^@?[a-z0-9.-]+\.[a-z]{2,}$")


@router.put("/college/settings")
async def college_settings(body: CollegeSettings, member: StaffDep, session: SessionDep) -> dict:
    need(member, "manage_staff")
    org = await session.get(Organization, member.org_id)
    org.domain = (body.domain or "").lower().lstrip("@") or None
    await session.commit()
    return {"domain": org.domain}


# ---------- students and the pipeline ----------


def _placement_out(p: CampusPlacement, name: str | None = None) -> dict:
    return {
        "id": str(p.id),
        "student": name,
        "user_id": str(p.user_id),
        "job_id": str(p.job_id) if p.job_id else None,
        "company": p.company,
        "title": p.title,
        "stage": p.stage,
        "stage_label": pc.STAGE_LABEL.get(p.stage, p.stage),
        "source": p.source,
        "match_score": p.match_score,
        "reasoning": p.reasoning or {},
        "feedback": p.feedback,
        "history": p.history or [],
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }


@router.get("/college/students")
async def students(member: StaffDep, session: SessionDep) -> dict:
    """Every student in your scope who shares their progress: academics, applications, interviews, offers and their
    pipeline stage per job. Students who don't share are counted, never listed."""
    org = await session.get(Organization, member.org_id)
    total = (await session.execute(select(func.count()).select_from(OrgMember).where(OrgMember.org_id == org.id, OrgMember.role == "student"))).scalar_one()
    async with officer_scope(org.id) as scoped:
        profiles = (await scoped.execute(select(Profile).join(OrgMember, OrgMember.user_id == Profile.user_id).where(OrgMember.org_id == org.id, OrgMember.role == "student"))).scalars().all()
        profiles = [p for p in profiles if pc.in_department(member, p.academics)]
        uids = [p.user_id for p in profiles]
        matches = (await scoped.execute(select(JobMatch).where(JobMatch.user_id.in_(uids)))).unique().scalars().all() if uids else []
        pipes = (await scoped.execute(select(CampusPlacement).where(CampusPlacement.org_id == org.id, CampusPlacement.user_id.in_(uids)))).scalars().all() if uids else []
    users = {u.id: u for u in (await session.execute(select(User).where(User.id.in_(uids)))).scalars()} if uids else {}
    rows = []
    for p in profiles:
        u = users.get(p.user_id)
        if u is None:
            continue
        mine = [m for m in matches if m.user_id == u.id]
        pl = [x for x in pipes if x.user_id == u.id]
        best = max((pc.PIPELINE.index(x.stage) for x in pl if x.stage in pc.PIPELINE), default=-1)
        rows.append(
            {
                "user_id": str(u.id),
                "name": u.name or u.email.split("@")[0],
                "email": u.email,
                "branch": (p.academics or {}).get("branch", ""),
                "grad_year": (p.academics or {}).get("grad_year"),
                "cgpa": (p.academics or {}).get("cgpa"),
                "matches": len(mine),
                "applied": sum(1 for m in mine if m.applied_at),
                "interviews": sum(m.outcome in ("interview", "offer") for m in mine),
                "offers": sum(m.outcome == "offer" for m in mine),
                "furthest": pc.PIPELINE[best] if best >= 0 else None,
                "furthest_label": pc.STAGE_LABEL[pc.PIPELINE[best]] if best >= 0 else "Preparing",
                "pipeline": [_placement_out(x) for x in sorted(pl, key=lambda x: x.updated_at or x.created_at, reverse=True)][:6],
                "last_active": u.last_seen_at.isoformat() if u.last_seen_at else None,
            }
        )
    session.add(AuditEvent(actor_user_id=member.user_id, action="staff_student_audit", subject=str(org.id), detail={"rows": len(rows), "role": pc.role_of(member), "department": member.department}))
    await session.commit()
    rows.sort(key=lambda r: (-(pc.PIPELINE.index(r["furthest"]) if r["furthest"] else -1), r["name"]))
    return {"total_students": total, "visible": len(rows), "scope": member.department if pc.role_of(member) != "tpo" and member.department else "Whole college", "students": rows}


@router.get("/college/pipeline")
async def pipeline(member: StaffDep, session: SessionDep, stage: str | None = None) -> dict:
    """The pipeline board: every placement in scope by stage, AI proposals first."""
    org = await session.get(Organization, member.org_id)
    async with officer_scope(org.id) as scoped:
        q = select(CampusPlacement).where(CampusPlacement.org_id == org.id)
        if stage:
            q = q.where(CampusPlacement.stage == stage)
        items = (await scoped.execute(q.order_by(CampusPlacement.updated_at.desc()).limit(500))).scalars().all()
        profs = {p.user_id: p for p in (await scoped.execute(select(Profile).where(Profile.user_id.in_([i.user_id for i in items])))).scalars()} if items else {}
    names = {u.id: (u.name or u.email.split("@")[0]) for u in (await session.execute(select(User).where(User.id.in_(list(profs))))).scalars()} if profs else {}
    items = [i for i in items if i.user_id in profs and pc.in_department(member, profs[i.user_id].academics)]
    counts: dict[str, int] = {}
    for i in items:
        counts[i.stage] = counts.get(i.stage, 0) + 1
    return {
        "stages": [{"key": s, "label": pc.STAGE_LABEL[s], "count": counts.get(s, 0)} for s in [*pc.PIPELINE, *pc.CLOSED]],
        "items": [_placement_out(i, names.get(i.user_id)) for i in items],
        "precision": await pc.precision_at_k(session, org.id),
    }


class Decision(BaseModel):
    decision: Literal["approve", "reject"]
    note: str = Field(default="", max_length=2000)


async def _placement(session, member: OrgMember, pid: uuid.UUID) -> CampusPlacement:
    p = await session.get(CampusPlacement, pid)
    if p is None or p.org_id != member.org_id:
        raise HTTPException(404, "No such placement")
    prof = (await session.execute(select(Profile).where(Profile.user_id == p.user_id))).scalar_one_or_none()
    if prof is None or not pc.in_department(member, prof.academics):
        raise HTTPException(404, "No such placement")
    from app.services.consent import has

    if not await has(session, p.user_id, "college_share"):
        raise HTTPException(404, "This student no longer shares their progress")
    return p


@router.post("/college/placements/{pid}/decision")
async def decide(pid: uuid.UUID, body: Decision, member: StaffDep, session: SessionDep) -> dict:
    """Approve an AI proposal (the student is shortlisted and told) or reject it (it counts against the AI's
    precision, which is the point)."""
    need(member, "approve")
    p = await _placement(session, member, pid)
    try:
        await pc.decide(session, p, member, body.decision == "approve", body.note)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    await session.commit()
    await session.refresh(p)
    return _placement_out(p)


class Move(BaseModel):
    stage: Literal["shortlisted", "round_1", "technical", "hr", "placed", "rejected", "withdrawn"]
    note: str = Field(default="", max_length=2000)


@router.put("/college/placements/{pid}/stage")
async def move_stage(pid: uuid.UUID, body: Move, member: StaffDep, session: SessionDep) -> dict:
    need(member, "move")
    p = await _placement(session, member, pid)
    try:
        await pc.move(session, p, member, body.stage, body.note)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    await session.commit()
    await session.refresh(p)
    return _placement_out(p)


class Feedback(BaseModel):
    note: str = Field(min_length=2, max_length=2000)


@router.post("/college/placements/{pid}/feedback")
async def add_feedback(pid: uuid.UUID, body: Feedback, member: StaffDep, session: SessionDep) -> dict:
    """Interview or mentoring feedback on a student's application (teachers can add it too)."""
    need(member, "feedback")
    p = await _placement(session, member, pid)
    p.feedback = body.note
    pc._hist(p, p.stage, member.user_id, f"Feedback: {body.note}")
    await pc.publish_staff(session, p.org_id, "campus_update", placement_id=str(p.id))
    await session.commit()
    await session.refresh(p)
    return _placement_out(p)


# ---------- jobs posted by the college, and AI proposals ----------


class CampusJobIn(BaseModel):
    title: str = Field(min_length=2, max_length=300)
    company: str = Field(min_length=1, max_length=200)
    url: str = Field(default="", max_length=1000)
    location: str = Field(default="", max_length=200)
    description: str = Field(min_length=40, max_length=20000)
    track: Literal["technical", "non_technical"] = "technical"
    kind: Literal["internship", "full_time"] = "internship"


@router.post("/college/jobs", status_code=201)
async def post_job(body: CampusJobIn, member: StaffDep, session: SessionDep) -> dict:
    """A job for this college's students only (from a recruiter's link or mail). It's embedded and matched against
    every sharing student in your scope right away; the best fits arrive as proposals for you to approve."""
    need(member, "post_job")
    await hit("campus_job", str(member.user_id))
    from app.embeddings import get_embedder
    from app.skills import extract_skills, job_embedding_text

    org = await session.get(Organization, member.org_id)
    if body.url and not body.url.startswith(("http://", "https://")):
        raise HTTPException(422, "The link must start with http:// or https://")
    job = Job(
        source="campus",
        external_id=f"campus-{uuid.uuid4().hex[:12]}",
        company=body.company.strip(),
        title=body.title.strip(),
        location=body.location.strip(),
        url=body.url.strip(),
        description=body.description.strip(),
        skills=extract_skills(f"{body.title}\n{body.description}"),
        track=body.track,
        org_id=org.id,
        posted_at=datetime.now(UTC),
        publisher=org.name[:80],
        legit_status="verified",
        legit_reasons=[f"Posted by {org.name}'s placement cell"],
        link_status="ok",
    )
    job.embedding = await get_embedder().embed_one(job_embedding_text(job.title, job.company, job.description))
    session.add(job)
    await session.flush()
    proposed = await pc.propose_for_job(session, org, job, member, member.user_id)
    session.add(AuditEvent(actor_user_id=member.user_id, action="campus_job", subject=str(job.id), detail={"proposed": proposed}))
    await session.commit()
    return {"id": str(job.id), "title": job.title, "company": job.company, "proposed": proposed}


@router.get("/college/jobs")
async def campus_jobs(member: StaffDep, session: SessionDep) -> list[dict]:
    jobs = (await session.execute(select(Job).where(Job.org_id == member.org_id).order_by(Job.posted_at.desc()).limit(100))).scalars().all()
    counts = dict((await session.execute(select(CampusPlacement.job_id, func.count()).where(CampusPlacement.org_id == member.org_id).group_by(CampusPlacement.job_id))).all())
    return [{"id": str(j.id), "title": j.title, "company": j.company, "url": j.url, "track": j.track, "posted_at": j.posted_at.isoformat() if j.posted_at else None, "placements": counts.get(j.id, 0)} for j in jobs]


@router.post("/college/jobs/{job_id}/rematch")
async def rematch(job_id: uuid.UUID, member: StaffDep, session: SessionDep) -> dict:
    need(member, "post_job")
    job = await session.get(Job, job_id)
    if job is None or job.org_id != member.org_id:
        raise HTTPException(404, "No such job")
    org = await session.get(Organization, member.org_id)
    n = await pc.propose_for_job(session, org, job, member, member.user_id)
    await session.commit()
    return {"proposed": n}


@router.post("/college/proposals/refresh")
async def refresh_proposals(member: StaffDep, session: SessionDep) -> dict:
    """Strong recent matches the students' own crews found (fit 70+) become proposals now (also runs hourly)."""
    need(member, "approve")
    org = await session.get(Organization, member.org_id)
    n = await pc.propose_from_index(session, org)
    await session.commit()
    return {"proposed": n}


# ---------- the student's side ----------


@router.get("/campus/placements")
async def my_placements(user: UserDep, session: SessionDep) -> list[dict]:
    """Your pipeline as your placement cell runs it (proposals they haven't approved yet aren't shown)."""
    rows = (await session.execute(select(CampusPlacement).where(CampusPlacement.user_id == user.id, CampusPlacement.stage != "proposed", CampusPlacement.stage != "dismissed").order_by(CampusPlacement.updated_at.desc()))).scalars().all()
    return [_placement_out(p) for p in rows]


# ---------- pricing enquiries ----------


class LeadIn(BaseModel):
    college: str = Field(min_length=2, max_length=200)
    name: str = Field(min_length=2, max_length=200)
    email: EmailStr
    role: str = Field(default="", max_length=60)
    students: int | None = Field(default=None, ge=1, le=200000)
    plan: Literal["pilot", "department", "institution", "university", ""] = ""
    message: str = Field(default="", max_length=3000)


@router.post("/campus/leads", status_code=201)
async def campus_lead(body: LeadIn, request: Request, session: SessionDep) -> dict:
    """A college asking for a workspace (from the campus pricing page). The JobPilot team replies by email."""
    await hit("campus_lead", client_ip(request))
    session.add(CampusLead(college=body.college.strip(), name=body.name.strip(), email=str(body.email), role=body.role.strip(), students=body.students, plan=body.plan, message=body.message.strip()))
    await session.commit()
    try:
        from app.config import settings
        from app.services.mailer import send_system_email

        for admin in settings.admin_emails:
            await send_system_email(admin, f"Campus enquiry: {body.college}", f"{body.name} ({body.role or 'staff'}, {body.email}) asked about the {body.plan or 'campus'} plan for {body.college}, about {body.students or '?'} students.\n\n{body.message}")
    except Exception:  # the enquiry is stored either way
        pass
    return {"ok": True}

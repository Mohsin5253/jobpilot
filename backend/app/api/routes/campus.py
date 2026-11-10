"""Campus placement mode (students) and the placement-cell dashboard (college officers)."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, or_, select

from app.api.deps import RealUserDep, SessionDep, UserDep
from app.models import CampusDrive, DriveStatus, Job, JobMatch, Organization, OrgMember, Profile, User
from app.services.campus import _dt, eligibility, prep_for, upcoming
from app.services.consent import grant, has, withdraw
from app.services.outcomes import insights, rejection_gaps

router = APIRouter(tags=["campus"])
DriveState = Literal["interested", "registered", "in_rounds", "selected", "rejected", "skipped"]


class Academics(BaseModel):
    college: str = Field(default="", max_length=200)
    branch: str = Field(default="", max_length=120)
    grad_year: int | None = Field(default=None, ge=2000, le=2100)
    cgpa: float | None = Field(default=None, ge=0, le=10)
    backlogs: int | None = Field(default=None, ge=0, le=50)


class Round(BaseModel):
    name: str = Field(max_length=80)
    type: Literal["aptitude", "coding", "technical", "group_discussion", "hr"] = "technical"
    date: datetime | None = None


class Eligibility(BaseModel):
    min_cgpa: float | None = Field(default=None, ge=0, le=10)
    branches: list[str] = Field(default_factory=list)
    max_backlogs: int | None = Field(default=None, ge=0)
    grad_years: list[int] = Field(default_factory=list)


class DriveIn(BaseModel):
    company: str = Field(min_length=1, max_length=200)
    role: str = Field(min_length=1, max_length=200)
    kind: Literal["internship", "full_time"] = "internship"
    compensation: str = Field(default="", max_length=100)
    eligibility: Eligibility = Field(default_factory=Eligibility)
    register_by: datetime | None = None
    rounds: list[Round] = Field(default_factory=list, max_length=10)
    notes: str = Field(default="", max_length=4000)


class StatusIn(BaseModel):
    status: DriveState
    round_index: int = Field(default=0, ge=0, le=10)


class JoinIn(BaseModel):
    invite_code: str = Field(min_length=4, max_length=20)
    share_progress: bool = False


class ShareIn(BaseModel):
    share_progress: bool


def _drive_out(d: CampusDrive, st: DriveStatus | None, academics: dict, mine: bool) -> dict:
    ok, reasons = eligibility(d, academics)
    return {
        "id": str(d.id),
        "company": d.company,
        "role": d.role,
        "kind": d.kind,
        "compensation": d.compensation,
        "eligibility": d.eligibility,
        "register_by": d.register_by.isoformat() if d.register_by else None,
        "rounds": d.rounds,
        "notes": d.notes,
        "posted_by_college": d.org_id is not None,
        "editable": mine,
        "eligible": ok,
        "eligibility_notes": reasons,
        "status": st.status if st else "interested",
        "round_index": st.round_index if st else 0,
        "upcoming": upcoming(d),
        "prep": prep_for(d),
    }


async def _membership(session, user_id) -> tuple[OrgMember | None, Organization | None]:
    m = (await session.execute(select(OrgMember).where(OrgMember.user_id == user_id))).scalar_one_or_none()
    return m, (await session.get(Organization, m.org_id) if m else None)


async def _profile(session, user_id) -> Profile:
    return (await session.execute(select(Profile).where(Profile.user_id == user_id))).scalar_one()


@router.get("/campus")
async def campus(user: UserDep, session: SessionDep) -> dict:
    profile = await _profile(session, user.id)
    academics = profile.academics or {}
    member, org = await _membership(session, user.id)
    cond = [CampusDrive.user_id == user.id] + ([CampusDrive.org_id == member.org_id] if member else [])
    drives = (await session.execute(select(CampusDrive).where(or_(*cond)).order_by(CampusDrive.register_by.asc().nulls_last()))).scalars().all()
    statuses = {s.drive_id: s for s in (await session.execute(select(DriveStatus).where(DriveStatus.user_id == user.id))).scalars()}
    out = [_drive_out(d, statuses.get(d.id), academics, d.user_id == user.id) for d in drives]

    # One timeline: drive deadlines and rounds, off-campus applications, and internships up for PPO.
    events = []
    for d in drives:
        if d.register_by:
            events.append({"at": d.register_by.isoformat(), "kind": "deadline", "title": f"Register: {d.company} · {d.role}", "drive_id": str(d.id)})
        for r in d.rounds or []:
            if r.get("date"):
                events.append({"at": _dt(r["date"]).isoformat(), "kind": "round", "title": f"{r.get('name', 'Round')}: {d.company}", "drive_id": str(d.id)})
    apps = (
        await session.execute(
            select(JobMatch, Job).join(Job, Job.id == JobMatch.job_id).where(JobMatch.user_id == user.id, JobMatch.applied_at.is_not(None)).order_by(JobMatch.applied_at.desc()).limit(30)
        )
    ).unique().all()
    for m, j in apps:
        events.append({"at": m.applied_at.isoformat(), "kind": "off_campus", "title": f"Applied: {j.company} · {j.title}", "match_id": str(m.id), "outcome": m.outcome})
    events.sort(key=lambda e: e["at"])
    ppo = [
        {"match_id": str(m.id), "company": j.company, "title": j.title, "ppo_status": m.ppo_status}
        for m, j in apps
        if (m.outcome == "offer" and "intern" in j.title.lower()) or m.ppo_status != "none"
    ]
    return {
        "academics": academics,
        "college": {"name": org.name, "role": member.role, "sharing": await has(session, user.id, "college_share")} if org else None,
        "drives": out,
        "timeline": events,
        "ppo": ppo,
        "summary": {
            "eligible_upcoming": sum(1 for d in out if d["eligible"] and d["upcoming"]),
            "in_rounds": sum(1 for d in out if d["status"] in ("registered", "in_rounds")),
            "selected": sum(1 for d in out if d["status"] == "selected"),
            "off_campus_applied": len(apps),
        },
    }


@router.put("/campus/academics")
async def set_academics(body: Academics, user: UserDep, session: SessionDep) -> dict:
    profile = await _profile(session, user.id)
    profile.academics = body.model_dump()
    await session.commit()
    return profile.academics


@router.post("/campus/drives", status_code=status.HTTP_201_CREATED)
async def add_drive(body: DriveIn, user: UserDep, session: SessionDep) -> dict:
    data = body.model_dump(mode="json")
    d = CampusDrive(user_id=user.id, **{**data, "register_by": body.register_by})
    session.add(d)
    await session.commit()
    return _drive_out(d, None, (await _profile(session, user.id)).academics or {}, True)


@router.delete("/campus/drives/{drive_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_drive(drive_id: uuid.UUID, user: UserDep, session: SessionDep) -> None:
    await session.execute(delete(CampusDrive).where(CampusDrive.id == drive_id, CampusDrive.user_id == user.id))
    await session.commit()


@router.put("/campus/drives/{drive_id}/status")
async def set_status(drive_id: uuid.UUID, body: StatusIn, user: UserDep, session: SessionDep) -> dict:
    d = await session.get(CampusDrive, drive_id)
    member, _ = await _membership(session, user.id)
    if d is None or not (d.user_id == user.id or (member and d.org_id == member.org_id)):
        raise HTTPException(404, "Drive not found")
    st = (await session.execute(select(DriveStatus).where(DriveStatus.drive_id == drive_id, DriveStatus.user_id == user.id))).scalar_one_or_none()
    if st is None:
        st = DriveStatus(drive_id=drive_id, user_id=user.id)
        session.add(st)
    st.status, st.round_index = body.status, body.round_index
    await session.commit()
    return _drive_out(d, st, (await _profile(session, user.id)).academics or {}, d.user_id == user.id)


@router.post("/campus/join")
async def join_college(body: JoinIn, user: RealUserDep, session: SessionDep) -> dict:
    org = (await session.execute(select(Organization).where(func.upper(Organization.invite_code) == body.invite_code.strip().upper()))).scalar_one_or_none()
    if org is None:
        raise HTTPException(404, "That invite code doesn't match a college")
    existing, _ = await _membership(session, user.id)
    if existing:
        raise HTTPException(409, "You're already in a college. Leave it first.")
    session.add(OrgMember(org_id=org.id, user_id=user.id, role="student"))
    if body.share_progress:
        await grant(session, user.id, "college_share")
    await session.commit()
    return {"college": org.name}


@router.put("/campus/share")
async def set_share(body: ShareIn, user: RealUserDep, session: SessionDep) -> dict:
    if body.share_progress:
        await grant(session, user.id, "college_share")
    else:
        await withdraw(session, user.id, "college_share")
    await session.commit()
    return {"sharing": body.share_progress}


@router.post("/campus/leave", status_code=status.HTTP_204_NO_CONTENT)
async def leave_college(user: RealUserDep, session: SessionDep) -> None:
    await session.execute(delete(OrgMember).where(OrgMember.user_id == user.id))
    await withdraw(session, user.id, "college_share")
    await session.commit()


# ---------- Placement cell ----------


async def officer(user: UserDep, session: SessionDep) -> OrgMember:
    m = (await session.execute(select(OrgMember).where(OrgMember.user_id == user.id, OrgMember.role == "officer"))).scalar_one_or_none()
    if m is None:
        raise HTTPException(403, "For placement-cell officers only")
    return m


OfficerDep = Annotated[OrgMember, Depends(officer)]


@router.get("/college")
async def college_dashboard(member: OfficerDep, session: SessionDep) -> dict:
    """Cohort view. Aggregates cover every student; names and per-student rows only those who agreed to share."""
    org = await session.get(Organization, member.org_id)
    students = (
        await session.execute(select(User, Profile).join(OrgMember, OrgMember.user_id == User.id).join(Profile, Profile.user_id == User.id).where(OrgMember.org_id == org.id, OrgMember.role == "student"))
    ).all()
    ids = [u.id for u, _ in students]
    sharing = {u.id for u, _ in students if await has(session, u.id, "college_share")}
    week = datetime.now(UTC) - timedelta(days=7)
    cohort = await insights(session, ids) if ids else None
    matches = (await session.execute(select(JobMatch).where(JobMatch.user_id.in_(ids), JobMatch.applied_at.is_not(None)))).unique().scalars().all() if ids else []
    drives = (await session.execute(select(CampusDrive).where(CampusDrive.org_id == org.id).order_by(CampusDrive.register_by.asc().nulls_last()))).scalars().all()
    drive_rows = []
    for d in drives:
        regs = (await session.execute(select(DriveStatus.status, func.count()).where(DriveStatus.drive_id == d.id).group_by(DriveStatus.status))).all()
        eligible = sum(1 for _, p in students if eligibility(d, p.academics or {})[0])
        drive_rows.append({**_drive_out(d, None, {}, True), "eligible_students": eligible, "statuses": dict(regs)})
    per_student = []
    for u, p in students:
        if u.id not in sharing:
            continue
        mine = [m for m in matches if m.user_id == u.id]
        per_student.append(
            {
                "name": u.name or u.email.split("@")[0],
                "email": u.email,
                "branch": (p.academics or {}).get("branch", ""),
                "cgpa": (p.academics or {}).get("cgpa"),
                "applications": len(mine),
                "interviews": sum(m.outcome in ("interview", "offer") for m in mine),
                "offers": sum(m.outcome == "offer" for m in mine),
                "ppo": sum(m.ppo_status == "converted" for m in mine),
                "last_active": u.last_seen_at.isoformat() if u.last_seen_at else None,
            }
        )
    return {
        "college": {"name": org.name, "invite_code": org.invite_code},
        "students": len(students),
        "sharing": len(sharing),
        "active_7d": sum(1 for u, _ in students if u.last_seen_at and u.last_seen_at >= week),
        "cohort": cohort,
        "offers": sum(m.outcome == "offer" for m in matches),
        "ppo_converted": sum(m.ppo_status == "converted" for m in matches),
        "top_gaps": rejection_gaps(list(matches)),
        "drives": drive_rows,
        "per_student": per_student,
    }


@router.post("/college/drives", status_code=status.HTTP_201_CREATED)
async def post_drive(body: DriveIn, member: OfficerDep, session: SessionDep) -> dict:
    d = CampusDrive(org_id=member.org_id, **{**body.model_dump(mode="json"), "register_by": body.register_by})
    session.add(d)
    await session.commit()
    return _drive_out(d, None, {}, True)


@router.delete("/college/drives/{drive_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_drive(drive_id: uuid.UUID, member: OfficerDep, session: SessionDep) -> None:
    await session.execute(delete(CampusDrive).where(CampusDrive.id == drive_id, CampusDrive.org_id == member.org_id))
    await session.commit()

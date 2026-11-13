"""Campus profile, in the student app (students never enter the staff portal).

A student joins their college by claiming the roster invite the college imported (college email + one-time code: the
programme and batch come from the college and are locked) or by picking college -> programme -> admission year
themselves (pending until staff of that programme confirm it). A full level puts the request on a waitlist and tells
the TPO / HOD; access is never silently blocked.

They add exactly three kinds of entries: internships, roles and awards, each self-reported until staff of their
department verify it. Academic fields (score, programme, roll no, pending subjects) are the college's and read-only.
Staff see these entries by name only while the student shares with their college; otherwise only in counts.
"""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, EmailStr, Field, ValidationError
from sqlalchemy import func, select, text

from app.api.deps import RealUserDep, UserDep
from app.campus import otp
from app.campus.access import student_session
from app.campus.achievements import CYBERCRIME_NOTE, dedupe_key, offer_letter_flags, parse
from app.campus.ids import uuid7
from app.campus.jobs import email_hash
from app.campus.models import Batch, Campus, CampusMembership, CampusRollup, CapacityAllocation, Degree, Department, ProofFile, Program, RosterStudent, StudentAchievement
from app.db import session_scope
from app.models import Notification
from app.services.ratelimit import hit

router = APIRouter(prefix="/campus-profile", tags=["campus-profile"])
LIMIT_ENTRIES = 300


async def _active_membership(user_id: uuid.UUID) -> CampusMembership | None:
    async with session_scope() as s:
        rows = (await s.execute(select(CampusMembership).where(CampusMembership.user_id == user_id, CampusMembership.kind == "student", CampusMembership.status.in_(["active", "pending", "waitlisted"])).order_by(CampusMembership.created_at.desc()))).scalars().all()
    return next((m for m in rows if m.status == "active"), rows[0] if rows else None)


@router.get("")
async def overview(user: UserDep) -> dict:
    from app.services.consent import has

    m = await _active_membership(user.id)
    out: dict = {"membership": None, "record": None, "achievements": [], "shares_with_college": False}
    async with session_scope() as s:
        out["shares_with_college"] = await has(s, user.id, "college_share")
        if m:
            c = await s.get(Campus, m.campus_id)
            prog = await s.get(Program, m.program_id) if m.program_id else None
            deg = await s.get(Degree, prog.degree_id) if prog else None
            dept = await s.get(Department, m.department_id) if m.department_id else None
            bat = await s.get(Batch, m.batch_id) if m.batch_id else None
            from app.campus.models import display_name

            out["membership"] = {"id": str(m.id), "campus_id": str(c.id), "campus": display_name(c), "status": m.status, "department": dept.name if dept else None,
                                 "program": f"{deg.abbreviation} {prog.specialisation}".strip() if prog and deg else None, "batch": f"{bat.admission_year}–{bat.graduation_year}" if bat else None,
                                 "locked": bool(m.roster_student_id), "labels": {"student_id": c.student_id_label, "pending_subjects": c.pending_subjects_label}}
    async with student_session(user.id) as s:
        rec = (await s.execute(select(RosterStudent).where(RosterStudent.claimed_user_id == user.id))).scalars().first()
        if rec:
            out["record"] = {"student_id": rec.student_id_at_institution, "name": rec.name, "score": float(rec.score_value) if rec.score_value is not None else None,
                             "score_scale": rec.score_scale, "pending_subjects": rec.pending_subjects, "graduation_year": rec.graduation_year, "current_term": rec.current_term,
                             "from": "your college" if rec.source != "student_legacy" else "you (self-reported earlier)", "editable": False}
        rows = (await s.execute(select(StudentAchievement).where(StudentAchievement.user_id == user.id).order_by(StudentAchievement.start_date.desc().nulls_last()))).scalars().all()
    from app.api.routes.campus_staff import _achievement
    from app.campus.storage import signed_url

    out["achievements"] = [_achievement(a, url=signed_url(a.campus_id, a.proof_file_id, user.id) if a.proof_file_id else None) for a in rows]
    out["sharing_note"] = "Shared with your college only if you allow it. Change this in Settings."
    return out


# ---------- joining a college ----------


@router.get("/colleges")
async def colleges(user: UserDep, q: str) -> list[dict]:
    term = q.strip().lower()[:80]
    if len(term) < 2:
        return []
    async with session_scope() as s:
        rows = (await s.execute(select(Campus).where(func.lower(Campus.name + " " + Campus.branch).like(f"%{term}%"), Campus.status == "active").order_by(Campus.name, Campus.branch).limit(20))).scalars().all()
    from app.campus.models import display_name

    return [{"id": str(c.id), "name": display_name(c), "city": c.city, "state": c.state} for c in rows]


@router.get("/colleges/{campus_id}/programs")
async def college_programs(campus_id: uuid.UUID, user: UserDep) -> list[dict]:
    async with session_scope() as s:
        rows = (await s.execute(select(Program, Degree, Department).join(Degree, Degree.id == Program.degree_id).join(Department, Department.id == Program.department_id).where(Program.campus_id == campus_id))).all()
    return [{"id": str(p.id), "name": f"{d.abbreviation} {p.specialisation}".strip(), "degree": d.name, "department": dep.name, "department_id": str(dep.id)} for p, d, dep in rows]


async def place_or_waitlist(s, m: CampusMembership) -> str:
    """'active', or 'waitlisted' when any level above the student is full (TPO and HOD are told). Never a silent block."""
    caps = {(a.level, a.ref_id): a.capacity for a in (await s.execute(select(CapacityAllocation).where(CapacityAllocation.campus_id == m.campus_id))).scalars()}
    used = {(r.level, r.ref_id): r.value for r in (await s.execute(select(CampusRollup).where(CampusRollup.campus_id == m.campus_id, CampusRollup.metric == "students"))).scalars()}
    prog = await s.get(Program, m.program_id) if m.program_id else None
    checks = [("campus", m.campus_id, ""), ("department", m.department_id, str(m.department_id)), ("program", m.program_id, str(m.program_id)), ("batch", m.batch_id, str(m.batch_id))]
    if prog:
        checks.append(("degree", prog.degree_id, str(prog.degree_id)))
    full = [lv for lv, ref, key in checks if ref and (lv, ref) in caps and used.get((lv, key), 0) >= caps[(lv, ref)]]
    if m.department_id and "department" not in full:
        # Department plan: an exact count, not the 15-minute rollup, with the department row locked so two students
        # joining at once can't both take the last seat.
        limit = (await s.execute(select(Department.plan_limit).where(Department.id == m.department_id).with_for_update())).scalar_one_or_none()
        if limit:
            taken = (await s.execute(select(func.count()).select_from(CampusMembership).where(
                CampusMembership.campus_id == m.campus_id, CampusMembership.department_id == m.department_id, CampusMembership.kind == "student",
                CampusMembership.status == "active", CampusMembership.id != m.id))).scalar_one()
            if taken >= limit:
                full.append("department")
    if not full:
        return "active"
    staff = (await s.execute(select(CampusMembership.user_id).where(CampusMembership.campus_id == m.campus_id, CampusMembership.kind == "staff", CampusMembership.status == "active", CampusMembership.role.in_(["tpo", "principal", "hod"])))).scalars().all()
    for u in staff:
        s.add(Notification(user_id=u, kind="campus", title="A student is on the waitlist", body=f"The {full[0]} is at capacity. Raise it in Campus → Setup → Capacity to admit them."))
    return "waitlisted"


class JoinIn(BaseModel):
    campus_id: uuid.UUID
    program_id: uuid.UUID
    admission_year: int = Field(ge=1990, le=2100)


@router.post("/join")
async def join(body: JoinIn, user: RealUserDep) -> dict:
    """Self-selected programme: pending until the HOD / faculty of that programme confirm, so nobody can put themselves
    in another department to see its drives."""
    async with session_scope() as s:
        p = await s.get(Program, body.program_id)
        if p is None or p.campus_id != body.campus_id:
            raise HTTPException(404, "No such programme at this college")
        existing = (await s.execute(select(CampusMembership).where(CampusMembership.campus_id == body.campus_id, CampusMembership.user_id == user.id, CampusMembership.kind == "student"))).scalar_one_or_none()
        if existing and existing.status in ("active", "pending", "waitlisted"):
            raise HTTPException(409, "You've already joined this college")
        bat = (await s.execute(select(Batch).where(Batch.campus_id == body.campus_id, Batch.program_id == p.id, Batch.admission_year == body.admission_year))).scalar_one_or_none()
        campus = await s.get(Campus, body.campus_id)
        from app.services.consent import has

        shares = await has(s, user.id, "college_share")
        if existing:
            m = existing
        else:
            m = CampusMembership(campus_id=body.campus_id, id=uuid7(), institution_id=campus.institution_id, user_id=user.id, kind="student")
            s.add(m)
        m.status, m.department_id, m.program_id, m.batch_id, m.shares_with_college = "pending", p.department_id, p.id, bat.id if bat else None, shares
    return {"status": "pending", "detail": "Your department confirms your programme next. Until then you're in no department's lists."}


class ClaimStart(BaseModel):
    campus_id: uuid.UUID
    college_email: EmailStr


@router.post("/claim/start")
async def claim_start(body: ClaimStart, user: RealUserDep) -> dict:
    await hit("mail_verify", str(user.id))
    async with session_scope() as s:
        r = (await s.execute(select(RosterStudent.id).where(RosterStudent.campus_id == body.campus_id, RosterStudent.college_email_hash == email_hash(str(body.college_email)), RosterStudent.claimed_user_id.is_(None)))).first()
    if r is None:  # same answer whether or not the address is on the roster: no roster enumeration
        return {"otp_sent_to": str(body.college_email)}
    await otp.issue(user.id, str(body.college_email), "roster_claim", body.campus_id)
    return {"otp_sent_to": str(body.college_email)}


class ClaimVerify(BaseModel):
    otp: str = Field(min_length=6, max_length=6)


@router.post("/claim/verify")
async def claim_verify(body: ClaimVerify, user: RealUserDep) -> dict:
    row = await otp.check(user.id, "roster_claim", body.otp)
    from app.services.consent import has

    async with session_scope() as s:
        r = (await s.execute(select(RosterStudent).where(RosterStudent.campus_id == row.campus_id, RosterStudent.college_email_hash == email_hash(row.email)).with_for_update())).scalar_one_or_none()
        if r is None or (r.claimed_user_id and r.claimed_user_id != user.id):
            raise HTTPException(409, "This record is already linked to another account. Ask your placement cell.")
        r.claimed_user_id, r.claimed_at = user.id, datetime.now(UTC)
        campus = await s.get(Campus, row.campus_id)
        m = (await s.execute(select(CampusMembership).where(CampusMembership.campus_id == row.campus_id, CampusMembership.user_id == user.id, CampusMembership.kind == "student"))).scalar_one_or_none()
        if m is None:
            m = CampusMembership(campus_id=row.campus_id, id=uuid7(), institution_id=campus.institution_id, user_id=user.id, kind="student")
            s.add(m)
        m.department_id, m.program_id, m.batch_id, m.roster_student_id = r.department_id, r.program_id, r.batch_id, r.id
        m.shares_with_college = await has(s, user.id, "college_share")
        m.status = await place_or_waitlist(s, m)
        status = m.status
        if status == "active":
            from app.api.routes.campus_staff import sync_legacy

            await sync_legacy(s, row.campus_id, user.id, "student")
    return {"status": status, "detail": "Linked to your college's record. Your programme and academics come from the college and can't be changed here."}


# ---------- achievements ----------


def _owner_scope(m: CampusMembership) -> dict:
    return {"department_id": m.department_id, "program_id": m.program_id, "batch_id": m.batch_id}


@router.post("/achievements", status_code=201)
async def add_achievement(body: dict, user: RealUserDep) -> dict:
    """Only internships, roles and awards, and only their own fields: anything else (cgpa, branch, status...) is a 400."""
    try:
        entry = parse(body)
    except (ValidationError, ValueError) as exc:
        raise HTTPException(400, _err(exc)) from exc
    m = await _active_membership(user.id)
    if m is None:
        raise HTTPException(409, "Join your college first (Campus profile → Join)")
    async with student_session(user.id) as s:
        n = (await s.execute(select(func.count()).select_from(StudentAchievement).where(StudentAchievement.user_id == user.id))).scalar_one()
        if n >= LIMIT_ENTRIES:
            raise HTTPException(409, f"Up to {LIMIT_ENTRIES} entries")
        data = entry.model_dump()
        a = StudentAchievement(campus_id=m.campus_id, id=uuid7(), user_id=user.id, dedupe_key=dedupe_key(entry), shares_with_college=m.shares_with_college, **_owner_scope(m),
                               **{k: v for k, v in data.items() if k in StudentAchievement.__table__.columns.keys()})
        s.add(a)
        try:
            await s.flush()
        except Exception as exc:
            raise HTTPException(409, "You've already added this (same event, date and position)") from exc
    from app.api.routes.campus_staff import _achievement

    return _achievement(a)


@router.put("/achievements/{campus_id}/{achievement_id}")
async def edit_achievement(campus_id: uuid.UUID, achievement_id: uuid.UUID, body: dict, user: RealUserDep) -> dict:
    """Editing a verified entry makes it self-reported again (enforced in the database)."""
    try:
        entry = parse(body)
    except (ValidationError, ValueError) as exc:
        raise HTTPException(400, _err(exc)) from exc
    async with student_session(user.id) as s:
        a = (await s.execute(select(StudentAchievement).where(StudentAchievement.campus_id == campus_id, StudentAchievement.id == achievement_id))).scalar_one_or_none()
        if a is None:  # someone else's entry is invisible here: row-level security
            raise HTTPException(404, "No such entry")
        if a.kind != entry.kind:
            raise HTTPException(400, "An entry can't change its kind: add a new one")
        for k, v in entry.model_dump().items():
            if k in StudentAchievement.__table__.columns.keys():
                setattr(a, k, v)
        a.dedupe_key = dedupe_key(entry)
        await s.flush()
        await s.refresh(a)
    from app.api.routes.campus_staff import _achievement

    return _achievement(a)


@router.delete("/achievements/{campus_id}/{achievement_id}", status_code=204)
async def delete_achievement(campus_id: uuid.UUID, achievement_id: uuid.UUID, user: RealUserDep) -> None:
    async with student_session(user.id) as s:
        proof = (await s.execute(text("DELETE FROM student_achievements WHERE campus_id = :c AND id = :i RETURNING proof_file_id"), {"c": campus_id, "i": achievement_id})).first()
        if proof is None:  # someone else's entry is invisible here: row-level security
            raise HTTPException(404, "No such entry")
        if proof.proof_file_id:
            await s.execute(text("DELETE FROM campus_proof_files WHERE campus_id = :c AND id = :i"), {"c": campus_id, "i": proof.proof_file_id})


@router.post("/achievements/{campus_id}/{achievement_id}/proof")
async def upload_proof(campus_id: uuid.UUID, achievement_id: uuid.UUID, user: RealUserDep, file: UploadFile = File(...)) -> dict:
    """PDF / JPG / PNG up to 5 MB: type-checked, images re-encoded without EXIF or GPS, stored encrypted. Internship
    offer letters are checked with the same rules as Scam Shield."""
    from app.campus.storage import ProofRejected, clean, encrypt, offer_letter_text, sha256

    await hit("resume_tools", str(user.id))
    raw = await file.read(5 * 1024 * 1024 + 1)
    try:
        data, mime = clean(raw, file.filename or "")
    except ProofRejected as exc:
        raise HTTPException(422, str(exc)) from exc
    flags: list[str] = []
    async with student_session(user.id) as s:
        a = (await s.execute(select(StudentAchievement).where(StudentAchievement.campus_id == campus_id, StudentAchievement.id == achievement_id))).scalar_one_or_none()
        if a is None:
            raise HTTPException(404, "No such entry")
        if a.kind == "internship":
            flags = offer_letter_flags(offer_letter_text(data, mime))
        f = ProofFile(campus_id=campus_id, id=uuid7(), user_id=user.id, mime=mime, size=len(data), sha256=sha256(data), data_enc=encrypt(data),
                      shares_with_college=a.shares_with_college, department_id=a.department_id, program_id=a.program_id, batch_id=a.batch_id)
        s.add(f)
        await s.flush()
        old = a.proof_file_id
        a.proof_file_id, a.verifier_flags = f.id, flags
        if old:
            await s.execute(text("DELETE FROM campus_proof_files WHERE campus_id = :c AND id = :i"), {"c": campus_id, "i": old})
    return {"ok": True, "flags": flags, "warning": (f"Check this offer: {'; '.join(flags)}. {CYBERCRIME_NOTE}" if flags else None)}


def _err(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        e = exc.errors()[0]
        loc = ".".join(str(x) for x in e.get("loc", ()) if not isinstance(x, int))
        if e.get("type") == "extra_forbidden":
            return f"'{loc.split('.')[-1]}' can't be set here (students add only internships, roles and awards; academic fields come from the college)"
        return f"{loc}: {e.get('msg', 'invalid')}".strip(": ")
    return str(exc)

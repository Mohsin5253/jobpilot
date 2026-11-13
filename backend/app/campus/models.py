"""Campus v2 tables. The large ones (memberships, college records, achievements, eligibility results) are hash-
partitioned on campus_id and keyed (campus_id, id) with time-ordered UUIDv7 ids; the staff audit log is partitioned by
month. Every campus table leads with campus_id. Row-level security lives in migration 0030 (see app/campus/access.py)."""

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, Date, DateTime, ForeignKey, Integer, LargeBinary, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.campus.ids import uuid7
from app.db import Base


def _now(**kw) -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), **kw)


class Institution(Base):
    __tablename__ = "institutions"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    name: Mapped[str] = mapped_column(String(300))
    type: Mapped[str] = mapped_column(String(30), default="standalone")  # university | college_group | standalone
    country_code: Mapped[str] = mapped_column(String(2), default="IN")
    website: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = _now()


class Campus(Base):
    """One college. Shares its id with the legacy `organizations` row, so drives and placements keep working."""

    __tablename__ = "campuses"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    institution_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("institutions.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(300))
    branch: Mapped[str] = mapped_column(String(120), default="")  # "Engineering", "Law": a branch of a same-named college
    plan: Mapped[str] = mapped_column(String(20), default="college")  # pilot | department | college | university
    native_name: Mapped[str] = mapped_column(String(300), default="")
    city: Mapped[str] = mapped_column(String(120), default="")
    state: Mapped[str] = mapped_column(String(120), default="")
    country_code: Mapped[str] = mapped_column(String(2), default="IN")
    campus_type: Mapped[str] = mapped_column(String(60), default="")
    aishe_id: Mapped[str | None] = mapped_column(String(20))
    website: Mapped[str | None] = mapped_column(String(200))
    allowed_email_domains: Mapped[list[str]] = mapped_column(ARRAY(String(120)), default=list, server_default="{}")
    student_id_label: Mapped[str] = mapped_column(String(40), default="Enrollment no.")
    pending_subjects_label: Mapped[str | None] = mapped_column(String(40))  # backlog, ATKT, KT, arrears, resit... or none
    score_scale: Mapped[dict[str, Any] | None] = mapped_column(JSONB)  # {"type": "cgpa", "max": 10} as the college gives it
    score_formula: Mapped[str | None] = mapped_column(Text)  # the college's own official conversion, if it provides one
    term_type: Mapped[str] = mapped_column(String(20), default="semester")
    locale: Mapped[str] = mapped_column(String(10), default="en-IN")
    timezone: Mapped[str] = mapped_column(String(40), default="Asia/Kolkata")
    total_capacity: Mapped[int | None] = mapped_column(Integer)
    staff_code_hash: Mapped[str | None] = mapped_column(String(64))
    staff_code_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="active")  # active | review (added by hand, not in AISHE)
    created_at: Mapped[datetime] = _now()


MAX_CAMPUS_STUDENTS = 2_000_000  # 20 lakh per college or branch; a university (all its branches) has no plan limit
DEPARTMENT_PLAN_STUDENTS = 300  # per department on the Department plan


def display_name(c: "Campus") -> str:
    return f"{c.name} — {c.branch}" if c.branch else c.name


class Department(Base):
    __tablename__ = "departments"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    campus_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("campuses.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(200))
    native_name: Mapped[str] = mapped_column(String(200), default="")
    staff_code_hash: Mapped[str | None] = mapped_column(String(64))  # the department's own staff code (joins this department only)
    staff_code_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    plan_limit: Mapped[int | None] = mapped_column(Integer)  # 300 on the Department plan
    created_at: Mapped[datetime] = _now()


class DepartmentRequest(Base):
    """A department registering itself (Department plan): HOD's institutional email confirmed, then verified by JobPilot."""

    __tablename__ = "department_requests"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    aishe_id: Mapped[str | None] = mapped_column(String(20))
    college_name: Mapped[str] = mapped_column(String(300))
    branch: Mapped[str] = mapped_column(String(120), default="")
    department_name: Mapped[str] = mapped_column(String(200))
    city: Mapped[str] = mapped_column(String(120), default="")
    state: Mapped[str] = mapped_column(String(120), default="")
    email: Mapped[str] = mapped_column(String(320))
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(12), default="email")  # email | pending | approved | rejected
    campus_id: Mapped[uuid.UUID | None] = mapped_column()
    department_id: Mapped[uuid.UUID | None] = mapped_column()
    reason: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = _now()
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_by: Mapped[uuid.UUID | None] = mapped_column()


class Field(Base):
    """ISCED-F 2013 field (broad / narrow / detailed), or a college's own specialisation mapped to one."""

    __tablename__ = "fields"
    code: Mapped[str] = mapped_column(String(10), primary_key=True)
    level: Mapped[str] = mapped_column(String(10))
    parent_code: Mapped[str | None] = mapped_column(String(10))
    name: Mapped[str] = mapped_column(String(200))
    names: Mapped[dict[str, str]] = mapped_column(JSONB, default=dict, server_default="{}")  # translations


class Degree(Base):
    __tablename__ = "degrees"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    name: Mapped[str] = mapped_column(String(200))
    abbreviation: Mapped[str] = mapped_column(String(60))
    isced_level: Mapped[int] = mapped_column(Integer)
    typical_years: Mapped[float | None] = mapped_column(Numeric(3, 1))
    term_type: Mapped[str] = mapped_column(String(20), default="semester")  # annual | semester | trimester | modular
    country_code: Mapped[str | None] = mapped_column(String(2))
    aishe_id: Mapped[str | None] = mapped_column(String(10))
    campus_id: Mapped[uuid.UUID | None] = mapped_column()  # a college's own degree (deleted with the campus in code)
    created_at: Mapped[datetime] = _now()


class CampusDegree(Base):
    __tablename__ = "campus_degrees"
    campus_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("campuses.id", ondelete="CASCADE"), primary_key=True)
    degree_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("degrees.id", ondelete="CASCADE"), primary_key=True)


class Program(Base):
    """A department running a degree in a field: the unit students belong to."""

    __tablename__ = "programs"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    campus_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("campuses.id", ondelete="CASCADE"))
    department_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("departments.id", ondelete="CASCADE"))
    degree_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("degrees.id"))
    field_code: Mapped[str | None] = mapped_column(ForeignKey("fields.code"))
    specialisation: Mapped[str] = mapped_column(String(200), default="")
    duration_years: Mapped[float | None] = mapped_column(Numeric(3, 1))
    term_type: Mapped[str] = mapped_column(String(20), default="semester")
    intake_per_year: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = _now()


class Batch(Base):
    __tablename__ = "batches"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    campus_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("campuses.id", ondelete="CASCADE"))
    program_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("programs.id", ondelete="CASCADE"))
    admission_year: Mapped[int] = mapped_column(Integer)
    graduation_year: Mapped[int] = mapped_column(Integer)
    current_term: Mapped[int | None] = mapped_column(Integer)
    term_override: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = _now()


class CapacityAllocation(Base):
    __tablename__ = "capacity_allocations"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    campus_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("campuses.id", ondelete="CASCADE"))
    level: Mapped[str] = mapped_column(String(12))  # campus | degree | department | program | batch
    ref_id: Mapped[uuid.UUID] = mapped_column()  # the campus, degree, department, program or batch id
    capacity: Mapped[int] = mapped_column(Integer)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    updated_at: Mapped[datetime] = _now(onupdate=func.now())


class CapacityHistory(Base):
    __tablename__ = "capacity_history"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    campus_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("campuses.id", ondelete="CASCADE"), index=True)
    level: Mapped[str] = mapped_column(String(12))
    ref_id: Mapped[uuid.UUID] = mapped_column()
    old: Mapped[int | None] = mapped_column(Integer)
    new: Mapped[int] = mapped_column(Integer)
    changed_by: Mapped[uuid.UUID | None] = mapped_column()
    changed_at: Mapped[datetime] = _now()


class StaffAssignment(Base):
    """Where a staff member works; their access scope comes only from approved assignments."""

    __tablename__ = "staff_assignments"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    campus_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("campuses.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(20))
    department_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("departments.id", ondelete="CASCADE"))
    program_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("programs.id", ondelete="CASCADE"))
    batch_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("batches.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(12), default="pending")  # pending | approved | revoked
    requested_at: Mapped[datetime] = _now()
    approved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CampusMembership(Base):
    """A student or a staff member at a campus. A person who is both has two rows (kind), approved separately."""

    __tablename__ = "campus_memberships"
    campus_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    institution_id: Mapped[uuid.UUID | None] = mapped_column()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(10))  # student | staff
    role: Mapped[str | None] = mapped_column(String(20))  # staff: tpo | principal | hod | faculty | coordinator | university_admin
    status: Mapped[str] = mapped_column(String(12), default="pending")  # invited | pending | active | waitlisted | deactivated
    department_id: Mapped[uuid.UUID | None] = mapped_column()
    program_id: Mapped[uuid.UUID | None] = mapped_column()
    batch_id: Mapped[uuid.UUID | None] = mapped_column()
    roster_student_id: Mapped[uuid.UUID | None] = mapped_column()
    shares_with_college: Mapped[bool] = mapped_column(Boolean, default=False)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)  # staff: institutional email confirmed by OTP
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _now(onupdate=func.now())


class RosterStudent(Base):
    """A college record: what the college uploads or confirms. The college owns it, so authorised staff in scope see it
    for every student (with or without a JobPilot account); students can't edit it."""

    __tablename__ = "roster_students"
    campus_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    student_id_at_institution: Mapped[str] = mapped_column(String(60))
    name: Mapped[str] = mapped_column(String(200))
    college_email_hash: Mapped[str | None] = mapped_column(String(64))  # the address itself isn't stored until claimed
    department_id: Mapped[uuid.UUID | None] = mapped_column()
    program_id: Mapped[uuid.UUID | None] = mapped_column()
    batch_id: Mapped[uuid.UUID | None] = mapped_column()
    score_value: Mapped[float | None] = mapped_column(Numeric(8, 3))
    score_scale: Mapped[dict[str, Any] | None] = mapped_column(JSONB)  # as the college gives it; never converted
    pending_subjects: Mapped[int | None] = mapped_column(Integer)
    graduation_year: Mapped[int | None] = mapped_column(Integer)
    current_term: Mapped[int | None] = mapped_column(Integer)
    custom: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    search_name: Mapped[str] = mapped_column(String(200), default="")  # lower(name), trigram-indexed
    claimed_user_id: Mapped[uuid.UUID | None] = mapped_column()
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source: Mapped[str] = mapped_column(String(20), default="roster")  # roster | staff | student_legacy
    updated_by: Mapped[uuid.UUID | None] = mapped_column()
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _now(onupdate=func.now())


class StudentAchievement(Base):
    """What a student adds: an internship, a role / position of responsibility, or an award. Self-reported until
    staff of the student's department verify it."""

    __tablename__ = "student_achievements"
    campus_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(12))  # internship | role | award
    sub_type: Mapped[str] = mapped_column(String(40), default="")  # internship: articleship, clinical posting, moot...
    category: Mapped[str] = mapped_column(String(40), default="")  # award: hackathon, moot court, sports...
    title: Mapped[str] = mapped_column(String(200))  # role/title, position, or event name
    organisation: Mapped[str] = mapped_column(String(200), default="")  # company, club, organiser
    level: Mapped[str | None] = mapped_column(String(20))  # college | inter_college | state | national | international
    position: Mapped[str | None] = mapped_column(String(20))  # winner | runner_up | finalist | participant
    mode: Mapped[str | None] = mapped_column(String(10))  # onsite | remote | hybrid
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    ongoing: Mapped[bool] = mapped_column(Boolean, default=False)
    stipend_inr: Mapped[int | None] = mapped_column(Integer)
    stipend_private: Mapped[bool] = mapped_column(Boolean, default=True)
    description: Mapped[str] = mapped_column(Text, default="")
    link: Mapped[str | None] = mapped_column(String(500))
    proof_file_id: Mapped[uuid.UUID | None] = mapped_column()
    status: Mapped[str] = mapped_column(String(14), default="self_reported")  # self_reported | verified | rejected
    reject_reason: Mapped[str | None] = mapped_column(String(300))
    verified_by: Mapped[uuid.UUID | None] = mapped_column()
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verifier_flags: Mapped[list[str]] = mapped_column(ARRAY(String(200)), default=list, server_default="{}")
    show_on_proof_page: Mapped[bool] = mapped_column(Boolean, default=False)
    shares_with_college: Mapped[bool] = mapped_column(Boolean, default=False)  # kept in sync with consent (trigger)
    department_id: Mapped[uuid.UUID | None] = mapped_column()
    program_id: Mapped[uuid.UUID | None] = mapped_column()
    batch_id: Mapped[uuid.UUID | None] = mapped_column()
    dedupe_key: Mapped[str] = mapped_column(String(300))
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _now(onupdate=func.now())


class ProofFile(Base):
    """A proof upload, encrypted in Postgres (the free storage option); app/campus/storage.py can move this to S3/R2
    by configuration. Images are re-encoded (no EXIF/GPS), PDFs with scripts or embedded files are refused."""

    __tablename__ = "campus_proof_files"
    campus_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    mime: Mapped[str] = mapped_column(String(40))
    size: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    data_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    object_key: Mapped[str | None] = mapped_column(String(300))
    shares_with_college: Mapped[bool] = mapped_column(Boolean, default=False)
    department_id: Mapped[uuid.UUID | None] = mapped_column()
    program_id: Mapped[uuid.UUID | None] = mapped_column()
    batch_id: Mapped[uuid.UUID | None] = mapped_column()
    created_at: Mapped[datetime] = _now()


class StaffAudit(Base):
    """Every staff login, view of an individual student, approval, verification and export. Partitioned by month."""

    __tablename__ = "staff_view_audit_log"
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True, server_default=func.now())
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    campus_id: Mapped[uuid.UUID] = mapped_column()
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column()
    action: Mapped[str] = mapped_column(String(24))
    subject_user_id: Mapped[uuid.UUID | None] = mapped_column()
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")


class CampusJob(Base):
    """Long work off the request path: roster imports, eligibility, rollups, matching, notifications."""

    __tablename__ = "campus_jobs"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    campus_id: Mapped[uuid.UUID] = mapped_column()
    kind: Mapped[str] = mapped_column(String(20))
    idempotency_key: Mapped[str] = mapped_column(String(120), unique=True)
    status: Mapped[str] = mapped_column(String(12), default="queued")  # queued | running | done | failed
    progress: Mapped[int] = mapped_column(Integer, default=0)
    total: Mapped[int] = mapped_column(Integer, default=0)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    result: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    blob: Mapped[bytes | None] = mapped_column(LargeBinary)  # the uploaded roster file (encrypted), dropped when done
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    run_after: Mapped[datetime] = _now()
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column()
    created_at: Mapped[datetime] = _now()
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CampusRollup(Base):
    """Pre-aggregated dashboard numbers per level: never COUNT(*) over lakhs of rows on a page load."""

    __tablename__ = "campus_rollups"
    campus_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    level: Mapped[str] = mapped_column(String(12), primary_key=True)  # campus | degree | department | program | batch
    ref_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    metric: Mapped[str] = mapped_column(String(40), primary_key=True)
    value: Mapped[int] = mapped_column(BigInteger, default=0)
    updated_at: Mapped[datetime] = _now()


class DriveEligibility(Base):
    __tablename__ = "drive_eligibility"
    campus_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    drive_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    roster_student_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    eligible: Mapped[bool] = mapped_column(Boolean)
    failed_rules: Mapped[list[str]] = mapped_column(ARRAY(String(60)), default=list, server_default="{}")
    department_id: Mapped[uuid.UUID | None] = mapped_column()
    program_id: Mapped[uuid.UUID | None] = mapped_column()
    batch_id: Mapped[uuid.UUID | None] = mapped_column()
    evaluated_at: Mapped[datetime] = _now()


class CustomField(Base):
    """A campus's own yes/no or number field for eligibility (e.g. "valid nursing registration")."""

    __tablename__ = "campus_custom_fields"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    campus_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("campuses.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(40))
    label: Mapped[str] = mapped_column(String(120))
    type: Mapped[str] = mapped_column(String(10), default="yes_no")  # yes_no | number | text


class EmailOtp(Base):
    __tablename__ = "email_otps"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    email: Mapped[str] = mapped_column(String(320))
    purpose: Mapped[str] = mapped_column(String(20))  # staff_email | staff_login | roster_claim
    code_hash: Mapped[str] = mapped_column(String(64))
    campus_id: Mapped[uuid.UUID | None] = mapped_column()
    department_id: Mapped[uuid.UUID | None] = mapped_column()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _now()


class RefInstitution(Base):
    """AISHE 2015-16 directory (colleges, standalone institutions, universities) for the setup wizard's search."""

    __tablename__ = "ref_institutions"
    aishe_id: Mapped[str] = mapped_column(String(20), primary_key=True)
    name: Mapped[str] = mapped_column(String(400))
    kind: Mapped[str] = mapped_column(String(12))
    state: Mapped[str] = mapped_column(String(80), default="")
    district: Mapped[str] = mapped_column(String(80), default="")
    university: Mapped[str] = mapped_column(String(300), default="")

"""Campus v2: tenancy (institutions, campuses, departments, programs, batches), fields and degrees for every discipline,
capacity, staff assignments, partitioned memberships / college records / achievements / audit log, background jobs,
rollups, row-level security on settings only, consent sync and verified-entry reset triggers. Backfills from the v1
tables (organizations, org_members, profiles.academics, consents) and seeds ISCED + AISHE reference data.

Revision ID: 1e7a3c9d5f28
Revises: 0d6f2b8c5e17
Create Date: 2026-11-13 18:00:00
"""

import csv
import gzip
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "1e7a3c9d5f28"
down_revision: Union[str, Sequence[str], None] = "0d6f2b8c5e17"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PARTS = int(__import__("os").getenv("CAMPUS_PARTITIONS", "32"))  # 32 in production; the test database uses 4 (faster TRUNCATE)
DATA = Path(__file__).resolve().parents[2] / "app" / "data" / "campus"

# ---- row-level security, on per-transaction settings only (no subqueries, no functions reading other tables) ----
ROLE = "coalesce(current_setting('app.campus_role', true), '')"
SYSTEM = f"{ROLE} = ''"
CAMPUS = "campus_id = ANY (coalesce(nullif(current_setting('app.campus_ids', true), ''), '{}')::uuid[])"
DEPTS = "coalesce(nullif(current_setting('app.dept_ids', true), ''), '{}')::uuid[]"
PROGS = "coalesce(nullif(current_setting('app.program_ids', true), ''), '{}')::uuid[]"
BATCHES = "coalesce(nullif(current_setting('app.batch_ids', true), ''), '{}')::uuid[]"
ME = "user_id = nullif(current_setting('app.user_id', true), '')::uuid"
SCOPE = (
    f"({ROLE} IN ('tpo', 'principal')"
    f" OR ({ROLE} IN ('hod', 'coordinator') AND department_id = ANY ({DEPTS}))"
    f" OR ({ROLE} = 'faculty' AND (batch_id = ANY ({BATCHES}) OR program_id = ANY ({PROGS}))))"
)
STAFF_ROW = f"({CAMPUS} AND {SCOPE})"


def _rls(table: str, staff_select: str | None, staff_update: str | None = None, student: str | None = None) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY {table}_system ON {table} FOR ALL TO PUBLIC USING ({SYSTEM}) WITH CHECK ({SYSTEM})")
    if staff_select:
        op.execute(f"CREATE POLICY {table}_staff_read ON {table} FOR SELECT TO PUBLIC USING ({staff_select})")
    if staff_update:
        op.execute(f"CREATE POLICY {table}_staff_update ON {table} FOR UPDATE TO PUBLIC USING ({staff_update}) WITH CHECK ({staff_update})")
    if student:
        op.execute(f"CREATE POLICY {table}_student ON {table} FOR ALL TO PUBLIC USING ({student}) WITH CHECK ({student})")


def _hash_partitions(table: str) -> None:
    for i in range(PARTS):
        op.execute(f"CREATE TABLE {table}_p{i:02d} PARTITION OF {table} FOR VALUES WITH (MODULUS {PARTS}, REMAINDER {i})")


def upgrade() -> None:
    bind = op.get_bind()
    try:
        op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
        trgm = True
    except Exception:  # noqa: BLE001 - search falls back to prefix matching
        trgm = False
    op.add_column("users", sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True))

    op.execute(
        """
        CREATE TABLE institutions (id uuid PRIMARY KEY, name varchar(300) NOT NULL, type varchar(30) NOT NULL DEFAULT 'standalone',
            country_code varchar(2) NOT NULL DEFAULT 'IN', website varchar(200), created_at timestamptz NOT NULL DEFAULT now());
        CREATE TABLE campuses (id uuid PRIMARY KEY, institution_id uuid NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
            name varchar(300) NOT NULL, native_name varchar(300) NOT NULL DEFAULT '', city varchar(120) NOT NULL DEFAULT '',
            state varchar(120) NOT NULL DEFAULT '', country_code varchar(2) NOT NULL DEFAULT 'IN', campus_type varchar(60) NOT NULL DEFAULT '',
            aishe_id varchar(20), website varchar(200), allowed_email_domains varchar(120)[] NOT NULL DEFAULT '{}',
            student_id_label varchar(40) NOT NULL DEFAULT 'Enrollment no.', pending_subjects_label varchar(40), score_scale jsonb,
            score_formula text, term_type varchar(20) NOT NULL DEFAULT 'semester', locale varchar(10) NOT NULL DEFAULT 'en-IN',
            timezone varchar(40) NOT NULL DEFAULT 'Asia/Kolkata', total_capacity integer, staff_code_hash varchar(64),
            staff_code_expires_at timestamptz, status varchar(20) NOT NULL DEFAULT 'active', created_at timestamptz NOT NULL DEFAULT now());
        CREATE INDEX ix_campuses_institution ON campuses (institution_id);
        CREATE TABLE departments (id uuid PRIMARY KEY, campus_id uuid NOT NULL REFERENCES campuses(id) ON DELETE CASCADE,
            name varchar(200) NOT NULL, native_name varchar(200) NOT NULL DEFAULT '', created_at timestamptz NOT NULL DEFAULT now());
        CREATE UNIQUE INDEX uq_departments_campus_name ON departments (campus_id, lower(name));
        CREATE TABLE fields (code varchar(10) PRIMARY KEY, level varchar(10) NOT NULL, parent_code varchar(10), name varchar(200) NOT NULL,
            names jsonb NOT NULL DEFAULT '{}');
        CREATE TABLE degrees (id uuid PRIMARY KEY, name varchar(200) NOT NULL, abbreviation varchar(60) NOT NULL, isced_level integer NOT NULL,
            typical_years numeric(3,1), term_type varchar(20) NOT NULL DEFAULT 'semester', country_code varchar(2), aishe_id varchar(10),
            campus_id uuid, created_at timestamptz NOT NULL DEFAULT now());  -- a college's own degree; no FK so seed rows survive TRUNCATE ... CASCADE
        CREATE INDEX ix_degrees_campus ON degrees (campus_id);
        CREATE TABLE campus_degrees (campus_id uuid REFERENCES campuses(id) ON DELETE CASCADE, degree_id uuid REFERENCES degrees(id) ON DELETE CASCADE,
            PRIMARY KEY (campus_id, degree_id));
        CREATE TABLE programs (id uuid PRIMARY KEY, campus_id uuid NOT NULL REFERENCES campuses(id) ON DELETE CASCADE,
            department_id uuid NOT NULL REFERENCES departments(id) ON DELETE CASCADE, degree_id uuid NOT NULL REFERENCES degrees(id),
            field_code varchar(10) REFERENCES fields(code), specialisation varchar(200) NOT NULL DEFAULT '', duration_years numeric(3,1),
            term_type varchar(20) NOT NULL DEFAULT 'semester', intake_per_year integer, created_at timestamptz NOT NULL DEFAULT now());
        CREATE INDEX ix_programs_campus_dept ON programs (campus_id, department_id);
        CREATE TABLE batches (id uuid PRIMARY KEY, campus_id uuid NOT NULL REFERENCES campuses(id) ON DELETE CASCADE,
            program_id uuid NOT NULL REFERENCES programs(id) ON DELETE CASCADE, admission_year integer NOT NULL, graduation_year integer NOT NULL,
            current_term integer, term_override boolean NOT NULL DEFAULT false, created_at timestamptz NOT NULL DEFAULT now());
        CREATE INDEX ix_batches_campus_program ON batches (campus_id, program_id);
        CREATE TABLE capacity_allocations (id uuid PRIMARY KEY, campus_id uuid NOT NULL REFERENCES campuses(id) ON DELETE CASCADE,
            level varchar(12) NOT NULL, ref_id uuid NOT NULL, capacity integer NOT NULL CHECK (capacity >= 0 AND capacity <= 4000000),
            updated_by uuid REFERENCES users(id) ON DELETE SET NULL, updated_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (campus_id, level, ref_id));
        CREATE TABLE capacity_history (id uuid PRIMARY KEY, campus_id uuid NOT NULL REFERENCES campuses(id) ON DELETE CASCADE,
            level varchar(12) NOT NULL, ref_id uuid NOT NULL, old integer, new integer NOT NULL, changed_by uuid, changed_at timestamptz NOT NULL DEFAULT now());
        CREATE INDEX ix_capacity_history_campus ON capacity_history (campus_id, changed_at);
        CREATE TABLE staff_assignments (id uuid PRIMARY KEY, campus_id uuid NOT NULL REFERENCES campuses(id) ON DELETE CASCADE,
            user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE, role varchar(20) NOT NULL,
            department_id uuid REFERENCES departments(id) ON DELETE CASCADE, program_id uuid REFERENCES programs(id) ON DELETE CASCADE,
            batch_id uuid REFERENCES batches(id) ON DELETE CASCADE, status varchar(12) NOT NULL DEFAULT 'pending',
            requested_at timestamptz NOT NULL DEFAULT now(), approved_by uuid REFERENCES users(id) ON DELETE SET NULL, approved_at timestamptz);
        CREATE INDEX ix_staff_assignments_campus_user ON staff_assignments (campus_id, user_id, status);
        CREATE TABLE campus_custom_fields (id uuid PRIMARY KEY, campus_id uuid NOT NULL REFERENCES campuses(id) ON DELETE CASCADE,
            key varchar(40) NOT NULL, label varchar(120) NOT NULL, type varchar(10) NOT NULL DEFAULT 'yes_no', UNIQUE (campus_id, key));
        CREATE INDEX ix_campus_custom_fields_campus_id ON campus_custom_fields (campus_id);
        CREATE TABLE email_otps (id uuid PRIMARY KEY, user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE, email varchar(320) NOT NULL,
            purpose varchar(20) NOT NULL, code_hash varchar(64) NOT NULL, campus_id uuid, expires_at timestamptz NOT NULL,
            attempts integer NOT NULL DEFAULT 0, used_at timestamptz, created_at timestamptz NOT NULL DEFAULT now());
        CREATE INDEX ix_email_otps_user_id ON email_otps (user_id);
        CREATE TABLE ref_institutions (aishe_id varchar(20) PRIMARY KEY, name varchar(400) NOT NULL, kind varchar(12) NOT NULL,
            state varchar(80) NOT NULL DEFAULT '', district varchar(80) NOT NULL DEFAULT '', university varchar(300) NOT NULL DEFAULT '');
        CREATE TABLE campus_jobs (id uuid PRIMARY KEY, campus_id uuid NOT NULL, kind varchar(20) NOT NULL, idempotency_key varchar(120) NOT NULL UNIQUE,
            status varchar(12) NOT NULL DEFAULT 'queued', progress integer NOT NULL DEFAULT 0, total integer NOT NULL DEFAULT 0,
            payload jsonb NOT NULL DEFAULT '{}', result jsonb NOT NULL DEFAULT '{}', blob bytea, attempts integer NOT NULL DEFAULT 0,
            run_after timestamptz NOT NULL DEFAULT now(), locked_at timestamptz, error text, created_by uuid,
            created_at timestamptz NOT NULL DEFAULT now(), finished_at timestamptz);
        CREATE INDEX ix_campus_jobs_queue ON campus_jobs (status, run_after) WHERE status IN ('queued', 'running');
        CREATE INDEX ix_campus_jobs_campus ON campus_jobs (campus_id, created_at);
        CREATE TABLE campus_rollups (campus_id uuid NOT NULL, level varchar(12) NOT NULL, ref_id varchar(40) NOT NULL, metric varchar(40) NOT NULL,
            value bigint NOT NULL DEFAULT 0, updated_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY (campus_id, level, ref_id, metric));
        """
    )

    # ---- the large tables: hash-partitioned on campus_id, keyed (campus_id, id) ----
    op.execute(
        """
        CREATE TABLE campus_memberships (campus_id uuid NOT NULL, id uuid NOT NULL, institution_id uuid, user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            kind varchar(10) NOT NULL, role varchar(20), status varchar(12) NOT NULL DEFAULT 'pending', department_id uuid, program_id uuid, batch_id uuid,
            roster_student_id uuid, shares_with_college boolean NOT NULL DEFAULT false, email_verified boolean NOT NULL DEFAULT false,
            created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (campus_id, id), UNIQUE (campus_id, user_id, kind)) PARTITION BY HASH (campus_id);
        CREATE INDEX ix_memberships_scope ON campus_memberships (campus_id, kind, status, department_id, batch_id, created_at, id);
        CREATE INDEX ix_memberships_user ON campus_memberships (user_id);
        CREATE TABLE roster_students (campus_id uuid NOT NULL, id uuid NOT NULL, student_id_at_institution varchar(60) NOT NULL, name varchar(200) NOT NULL,
            college_email_hash varchar(64), department_id uuid, program_id uuid, batch_id uuid, score_value numeric(8,3), score_scale jsonb,
            pending_subjects integer, graduation_year integer, current_term integer, custom jsonb NOT NULL DEFAULT '{}',
            search_name varchar(200) NOT NULL DEFAULT '', claimed_user_id uuid, claimed_at timestamptz, source varchar(20) NOT NULL DEFAULT 'roster',
            updated_by uuid, created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (campus_id, id), UNIQUE (campus_id, student_id_at_institution)) PARTITION BY HASH (campus_id);
        CREATE INDEX ix_roster_scope ON roster_students (campus_id, department_id, batch_id, created_at, id);
        CREATE INDEX ix_roster_program ON roster_students (campus_id, program_id, batch_id);
        CREATE INDEX ix_roster_claimed ON roster_students (claimed_user_id) WHERE claimed_user_id IS NOT NULL;
        CREATE INDEX ix_roster_email ON roster_students (campus_id, college_email_hash);
        CREATE TABLE student_achievements (campus_id uuid NOT NULL, id uuid NOT NULL, user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            kind varchar(12) NOT NULL CHECK (kind IN ('internship', 'role', 'award')), sub_type varchar(40) NOT NULL DEFAULT '',
            category varchar(40) NOT NULL DEFAULT '', title varchar(200) NOT NULL, organisation varchar(200) NOT NULL DEFAULT '',
            level varchar(20), position varchar(20), mode varchar(10), start_date date, end_date date, ongoing boolean NOT NULL DEFAULT false,
            stipend_inr integer, stipend_private boolean NOT NULL DEFAULT true, description text NOT NULL DEFAULT '', link varchar(500),
            proof_file_id uuid, status varchar(14) NOT NULL DEFAULT 'self_reported' CHECK (status IN ('self_reported', 'verified', 'rejected')),
            reject_reason varchar(300), verified_by uuid, verified_at timestamptz, verifier_flags varchar(200)[] NOT NULL DEFAULT '{}',
            show_on_proof_page boolean NOT NULL DEFAULT false, shares_with_college boolean NOT NULL DEFAULT false,
            department_id uuid, program_id uuid, batch_id uuid, dedupe_key varchar(300) NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
            CHECK (end_date IS NULL OR start_date IS NULL OR end_date >= start_date),
            PRIMARY KEY (campus_id, id), UNIQUE (campus_id, user_id, dedupe_key)) PARTITION BY HASH (campus_id);
        CREATE INDEX ix_achievements_queue ON student_achievements (campus_id, status, kind, created_at, id);
        CREATE INDEX ix_achievements_dash ON student_achievements (campus_id, department_id, kind, level, status);
        CREATE INDEX ix_achievements_user ON student_achievements (user_id);
        CREATE TABLE campus_proof_files (campus_id uuid NOT NULL, id uuid NOT NULL, user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            mime varchar(40) NOT NULL, size integer NOT NULL, sha256 varchar(64) NOT NULL, data_enc bytea, object_key varchar(300),
            shares_with_college boolean NOT NULL DEFAULT false, department_id uuid, program_id uuid, batch_id uuid,
            created_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY (campus_id, id)) PARTITION BY HASH (campus_id);
        CREATE INDEX ix_proof_user ON campus_proof_files (user_id);
        CREATE TABLE drive_eligibility (campus_id uuid NOT NULL, drive_id uuid NOT NULL, roster_student_id uuid NOT NULL, eligible boolean NOT NULL,
            failed_rules varchar(60)[] NOT NULL DEFAULT '{}', department_id uuid, program_id uuid, batch_id uuid,
            evaluated_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY (campus_id, drive_id, roster_student_id)) PARTITION BY HASH (campus_id);
        CREATE INDEX ix_drive_eligibility_dash ON drive_eligibility (campus_id, drive_id, eligible, department_id);
        CREATE TABLE staff_view_audit_log (at timestamptz NOT NULL DEFAULT now(), id uuid NOT NULL, campus_id uuid NOT NULL, actor_user_id uuid,
            action varchar(24) NOT NULL, subject_user_id uuid, detail jsonb NOT NULL DEFAULT '{}', PRIMARY KEY (at, id)) PARTITION BY RANGE (at);
        CREATE INDEX ix_staff_audit_campus ON staff_view_audit_log (campus_id, at);
        CREATE TABLE staff_view_audit_log_default PARTITION OF staff_view_audit_log DEFAULT;
        """
    )
    for t in ("campus_memberships", "roster_students", "student_achievements", "campus_proof_files", "drive_eligibility"):
        _hash_partitions(t)
    today = date.today().replace(day=1)
    for k in range(-1, 13):  # last month and the next twelve; the maintenance job keeps adding months
        y, m = divmod(today.month - 1 + k, 12)
        start = date(today.year + y, m + 1, 1)
        y2, m2 = divmod(start.month, 12)
        end = date(start.year + y2, m2 + 1, 1)
        op.execute(f"CREATE TABLE staff_view_audit_log_{start:%Y%m} PARTITION OF staff_view_audit_log FOR VALUES FROM ('{start}') TO ('{end}')")
    if trgm:
        op.execute("CREATE INDEX ix_roster_name_trgm ON roster_students USING gin (search_name gin_trgm_ops)")
        op.execute("CREATE INDEX ix_ref_institutions_trgm ON ref_institutions USING gin (lower(name) gin_trgm_ops)")

    # ---- triggers ----
    op.execute(
        """
        -- Consent to share with the college, copied onto every row RLS checks (no subquery in the policies).
        CREATE OR REPLACE FUNCTION jp_sync_college_share() RETURNS trigger AS $$
        DECLARE active boolean;
        BEGIN
          IF NEW.purpose <> 'college_share' THEN RETURN NEW; END IF;
          SELECT EXISTS (SELECT 1 FROM consents WHERE user_id = NEW.user_id AND purpose = 'college_share' AND withdrawn_at IS NULL) INTO active;
          UPDATE campus_memberships SET shares_with_college = active WHERE user_id = NEW.user_id AND kind = 'student' AND shares_with_college IS DISTINCT FROM active;
          UPDATE student_achievements SET shares_with_college = active WHERE user_id = NEW.user_id AND shares_with_college IS DISTINCT FROM active;
          UPDATE campus_proof_files SET shares_with_college = active WHERE user_id = NEW.user_id AND shares_with_college IS DISTINCT FROM active;
          RETURN NEW;
        END $$ LANGUAGE plpgsql;
        CREATE TRIGGER jp_sync_college_share AFTER INSERT OR UPDATE ON consents FOR EACH ROW EXECUTE FUNCTION jp_sync_college_share();

        -- Editing a verified entry makes it self-reported again, whatever code path changed it.
        CREATE OR REPLACE FUNCTION jp_achievement_reverify() RETURNS trigger AS $$
        BEGIN
          IF OLD.status = 'verified' AND NEW.status = 'verified' AND (
               NEW.title, NEW.organisation, NEW.kind, NEW.sub_type, NEW.category, NEW.level, NEW.position, NEW.mode, NEW.start_date,
               NEW.end_date, NEW.ongoing, NEW.stipend_inr, NEW.description, NEW.link, NEW.proof_file_id)
             IS DISTINCT FROM (
               OLD.title, OLD.organisation, OLD.kind, OLD.sub_type, OLD.category, OLD.level, OLD.position, OLD.mode, OLD.start_date,
               OLD.end_date, OLD.ongoing, OLD.stipend_inr, OLD.description, OLD.link, OLD.proof_file_id) THEN
            NEW.status := 'self_reported'; NEW.verified_by := NULL; NEW.verified_at := NULL;
          END IF;
          NEW.updated_at := now();
          RETURN NEW;
        END $$ LANGUAGE plpgsql;
        CREATE TRIGGER jp_achievement_reverify BEFORE UPDATE ON student_achievements FOR EACH ROW EXECUTE FUNCTION jp_achievement_reverify();

        -- Every capacity change is kept with who and when.
        CREATE OR REPLACE FUNCTION jp_capacity_history() RETURNS trigger AS $$
        BEGIN
          INSERT INTO capacity_history (id, campus_id, level, ref_id, old, new, changed_by, changed_at)
          VALUES (gen_random_uuid(), NEW.campus_id, NEW.level, NEW.ref_id, CASE WHEN TG_OP = 'UPDATE' THEN OLD.capacity END, NEW.capacity, NEW.updated_by, now());
          RETURN NEW;
        END $$ LANGUAGE plpgsql;
        CREATE TRIGGER jp_capacity_history AFTER INSERT OR UPDATE OF capacity ON capacity_allocations FOR EACH ROW EXECUTE FUNCTION jp_capacity_history();
        """
    )

    # ---- row-level security ----
    consented = f"({STAFF_ROW} AND shares_with_college)"
    # Staff see colleagues; students in scope by name only with consent, except a join request waiting for them to confirm.
    _rls(
        "campus_memberships",
        f"({CAMPUS} AND (kind = 'staff' OR ({SCOPE} AND (shares_with_college OR status IN ('pending', 'waitlisted')))))",
        f"({CAMPUS} AND kind = 'student' AND status IN ('pending', 'waitlisted', 'active') AND {SCOPE})",
        f"{ROLE} = 'student' AND {ME}",
    )
    _rls("roster_students", STAFF_ROW, f"({CAMPUS} AND {ROLE} IN ('tpo', 'principal'))", f"{ROLE} = 'student' AND claimed_user_id = nullif(current_setting('app.user_id', true), '')::uuid")
    _rls("student_achievements", consented, consented, f"{ROLE} = 'student' AND {ME}")
    _rls("campus_proof_files", consented, None, f"{ROLE} = 'student' AND {ME}")
    _rls("drive_eligibility", STAFF_ROW, None, None)
    _rls("staff_view_audit_log", f"({CAMPUS} AND {ROLE} IN ('tpo', 'principal'))", None, None)
    for t in ("departments", "programs", "batches", "staff_assignments", "capacity_allocations", "campus_rollups"):
        _rls(t, f"({CAMPUS} AND {ROLE} IN ('tpo', 'principal', 'hod', 'coordinator', 'faculty', 'university_admin'))", None, None)
    op.execute(
        """
        DO $$
        BEGIN
          IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'jobpilot_campus') THEN
            EXECUTE 'CREATE ROLE jobpilot_campus NOLOGIN NOBYPASSRLS';
          END IF;
          EXECUTE 'GRANT jobpilot_campus TO ' || quote_ident(current_user);
          EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE ON campus_memberships, roster_students, student_achievements, campus_proof_files,
                   drive_eligibility, staff_view_audit_log, departments, programs, batches, staff_assignments, capacity_allocations,
                   capacity_history, campus_rollups, campuses, institutions, degrees, campus_degrees, fields, campus_custom_fields,
                   campus_jobs, campus_drives, consents TO jobpilot_campus';
          EXECUTE 'GRANT SELECT ON users, ref_institutions TO jobpilot_campus';
        EXCEPTION WHEN insufficient_privilege THEN
          RAISE NOTICE 'jobpilot_campus role not created: policies still apply to the non-superuser app role';
        END $$;
        """
    )

    _seed_reference(bind)
    _backfill(bind)


def _seed_reference(bind) -> None:
    import uuid as _uuid

    from app.campus.taxonomy import EXTRA_DEGREES, all_fields

    op.bulk_insert(sa.table("fields", sa.column("code"), sa.column("level"), sa.column("parent_code"), sa.column("name")), all_fields())
    deg = sa.table("degrees", sa.column("id"), sa.column("name"), sa.column("abbreviation"), sa.column("isced_level"), sa.column("typical_years"),
                   sa.column("country_code"), sa.column("aishe_id"), sa.column("term_type"))
    rows = []
    years = {8: 3, 7: 2, 6: 3, 5: 2, 4: 1, 3: 2}
    with open(DATA / "aishe_programmes.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if not r["isced_level"]:
                continue
            lvl = int(r["isced_level"])
            rows.append({"id": _uuid.uuid4(), "name": r["name"], "abbreviation": r["abbreviation"], "isced_level": lvl, "typical_years": years.get(lvl),
                         "country_code": "IN", "aishe_id": r["aishe_id"], "term_type": "semester"})
    for name, abbr, lvl, yrs, country in EXTRA_DEGREES:
        rows.append({"id": _uuid.uuid4(), "name": name, "abbreviation": abbr, "isced_level": lvl, "typical_years": yrs, "country_code": country, "aishe_id": None, "term_type": "semester"})
    op.bulk_insert(deg, rows)
    inst = sa.table("ref_institutions", sa.column("aishe_id"), sa.column("name"), sa.column("kind"), sa.column("state"), sa.column("district"), sa.column("university"))
    batch: list[dict] = []
    with gzip.open(DATA / "aishe_colleges.csv.gz", "rt", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            batch.append({k: (r[k] or "")[:400] for k in ("aishe_id", "name", "kind", "state", "district", "university")})
            if len(batch) >= 5000:
                op.bulk_insert(inst, batch)
                batch = []
    if batch:
        op.bulk_insert(inst, batch)


def _backfill(bind) -> None:
    """v1 -> v2: each organization becomes a campus (same id) under its own institution; members become memberships;
    free-text departments become departments; the student-typed academics become self-reported college records
    (source=student_legacy) until the college imports its roster. Existing staff stay active (they were admitted
    under v1's rules); new staff go through verification and approval."""
    import json
    import uuid as _uuid

    from app.campus.ids import uuid7

    orgs = bind.execute(sa.text("SELECT id, name, domain, staff_code_hash FROM organizations")).all()
    for o in orgs:
        inst = uuid7()
        bind.execute(sa.text("INSERT INTO institutions (id, name, type) VALUES (:i, :n, 'standalone')"), {"i": inst, "n": o.name})
        bind.execute(
            sa.text("INSERT INTO campuses (id, institution_id, name, allowed_email_domains, staff_code_hash) VALUES (:id, :i, :n, :d, :h)"),
            {"id": o.id, "i": inst, "n": o.name, "d": [o.domain.lstrip("@")] if o.domain else [], "h": o.staff_code_hash},
        )
    depts: dict[tuple, _uuid.UUID] = {}
    members = bind.execute(sa.text(
        "SELECT m.org_id, m.user_id, m.role, m.department, p.academics, "
        "EXISTS (SELECT 1 FROM consents c WHERE c.user_id = m.user_id AND c.purpose = 'college_share' AND c.withdrawn_at IS NULL) AS shares "
        "FROM org_members m LEFT JOIN profiles p ON p.user_id = m.user_id"
    )).all()
    for m in members:
        dept_name = (m.department or (m.academics or {}).get("branch") or "").strip()
        dept_id = None
        if dept_name:
            key = (m.org_id, dept_name.lower())
            if key not in depts:
                depts[key] = uuid7()
                bind.execute(sa.text("INSERT INTO departments (id, campus_id, name) VALUES (:i, :c, :n) ON CONFLICT DO NOTHING"), {"i": depts[key], "c": m.org_id, "n": dept_name})
            dept_id = depts[key]
        staff = m.role != "student"
        role = {"teacher": "faculty", "officer": "tpo"}.get(m.role, m.role) if staff else None
        roster_id = None
        if not staff and m.academics:
            a = m.academics or {}
            roster_id = uuid7()
            bind.execute(
                sa.text(
                    "INSERT INTO roster_students (campus_id, id, student_id_at_institution, name, department_id, score_value, pending_subjects, "
                    "graduation_year, search_name, claimed_user_id, claimed_at, source) "
                    "SELECT :c, :i, :sid, coalesce(u.name, ''), :d, :score, :pend, :gy, lower(coalesce(u.name, '')), u.id, now(), 'student_legacy' FROM users u WHERE u.id = :u"
                ),
                {"c": m.org_id, "i": roster_id, "sid": f"legacy-{str(m.user_id)[:8]}", "d": dept_id, "score": a.get("cgpa"), "pend": a.get("backlogs"), "gy": a.get("grad_year"), "u": m.user_id},
            )
        bind.execute(
            sa.text(
                "INSERT INTO campus_memberships (campus_id, id, user_id, kind, role, status, department_id, roster_student_id, shares_with_college, email_verified) "
                "VALUES (:c, :i, :u, :k, :r, 'active', :d, :rs, :s, :ev)"
            ),
            {"c": m.org_id, "i": uuid7(), "u": m.user_id, "k": "staff" if staff else "student", "r": role, "d": dept_id, "rs": roster_id, "s": bool(m.shares) and not staff, "ev": staff},
        )
        if staff and role in ("hod", "faculty") and dept_id:
            bind.execute(
                sa.text("INSERT INTO staff_assignments (id, campus_id, user_id, role, department_id, status, approved_at) VALUES (:i, :c, :u, :r, :d, 'approved', now())"),
                {"i": uuid7(), "c": m.org_id, "u": m.user_id, "r": role, "d": dept_id},
            )
    _ = json, datetime, UTC


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS jp_sync_college_share ON consents; DROP FUNCTION IF EXISTS jp_sync_college_share()")
    for t in ("staff_view_audit_log", "drive_eligibility", "campus_proof_files", "student_achievements", "roster_students", "campus_memberships",
              "campus_rollups", "campus_jobs", "ref_institutions", "email_otps", "campus_custom_fields", "staff_assignments", "capacity_history",
              "capacity_allocations", "batches", "programs", "campus_degrees", "degrees", "fields", "departments", "campuses", "institutions"):
        op.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
    op.execute("DROP FUNCTION IF EXISTS jp_achievement_reverify(); DROP FUNCTION IF EXISTS jp_capacity_history()")
    op.drop_column("users", "email_verified_at")

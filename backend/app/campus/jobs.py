"""Campus background jobs on a Postgres queue (FOR UPDATE SKIP LOCKED: no extra service): roster imports, drive
eligibility, dashboard rollups. Each job has an idempotency key, retries with backoff, and progress the UI polls.
Nothing long ever runs inside an HTTP request."""

import csv
import hashlib
import io
import re
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text

from app.campus.ids import uuid7
from app.campus.models import Batch, Campus, CampusJob, Degree, Department, Program
from app.campus.rules import Record, evaluate
from app.db import session_scope
from app.logging import log

BATCH = 5000
MAX_ROWS = 200_000
MAX_ERRORS = 5000


async def enqueue(campus_id: uuid.UUID, kind: str, key: str, payload: dict | None = None, blob: bytes | None = None, by: uuid.UUID | None = None) -> uuid.UUID:
    """Queue a job, or return the existing one with the same idempotency key."""
    async with session_scope() as s:
        found = (await s.execute(select(CampusJob.id).where(CampusJob.idempotency_key == key))).scalar_one_or_none()
        if found:
            return found
        j = CampusJob(id=uuid7(), campus_id=campus_id, kind=kind, idempotency_key=key[:120], payload=payload or {}, blob=blob, created_by=by)
        s.add(j)
        return j.id


async def run_pending(limit: int = 5) -> int:
    """Claim and run up to `limit` due jobs. Called by the worker loop (and directly in tests)."""
    done = 0
    for _ in range(limit):
        async with session_scope() as s:
            j = (
                await s.execute(
                    select(CampusJob).where(CampusJob.status == "queued", CampusJob.run_after <= datetime.now(UTC)).order_by(CampusJob.created_at).limit(1).with_for_update(skip_locked=True)
                )
            ).scalar_one_or_none()
            if j is None:
                break
            j.status, j.locked_at, j.attempts = "running", datetime.now(UTC), j.attempts + 1
            job_id, kind = j.id, j.kind
        try:
            await HANDLERS[kind](job_id)
            async with session_scope() as s:
                row = await s.get(CampusJob, job_id)
                row.status, row.finished_at, row.blob = "done", datetime.now(UTC), None
        except Exception as exc:  # noqa: BLE001 - retried with backoff, then marked failed
            log.warning("campus.job_failed", kind=kind, job_id=str(job_id), error=type(exc).__name__)
            async with session_scope() as s:
                row = await s.get(CampusJob, job_id)
                row.error = f"{type(exc).__name__}: {str(exc)[:300]}"
                if row.attempts >= 3:
                    row.status, row.finished_at, row.blob = "failed", datetime.now(UTC), None
                else:
                    row.status, row.run_after = "queued", datetime.now(UTC) + timedelta(seconds=30 * 2 ** row.attempts)
        done += 1
    return done


async def _progress(job_id: uuid.UUID, progress: int, total: int | None = None, **result) -> None:
    async with session_scope() as s:
        j = await s.get(CampusJob, job_id)
        j.progress = progress
        if total is not None:
            j.total = total
        if result:
            j.result = {**(j.result or {}), **result}


# ---------- roster import ----------

ALIASES = {
    "student_id": ("student_id", "roll no", "roll number", "roll_no", "enrollment no", "enrolment no", "enrollment number", "registration no", "reg no", "prn", "usn", "student id", "admission no", "id"),
    "name": ("name", "student name", "full name"),
    "email": ("email", "college email", "email id", "institutional email"),
    "department": ("department", "dept", "branch", "stream", "discipline", "school"),
    "degree": ("degree", "programme", "program", "course"),
    "specialisation": ("specialisation", "specialization", "major"),
    "admission_year": ("admission year", "admission_year", "year of admission", "batch"),
    "graduation_year": ("graduation year", "graduation_year", "passing year", "pass out year", "year of passing"),
    "term": ("current year", "semester", "current semester", "term", "year"),
    "score": ("score", "cgpa", "gpa", "sgpa", "percentage", "marks", "aggregate"),
    "pending_subjects": ("pending subjects", "backlogs", "backlog", "atkt", "kt", "arrears", "supplementary", "resit", "carry over"),
}


def _header_map(header: list[str], custom_keys: list[str]) -> dict[int, str]:
    out = {}
    for i, h in enumerate(header):
        k = re.sub(r"\s+", " ", (h or "").strip().lower().replace("_", " "))
        for canon, names in ALIASES.items():
            if k in {n.replace("_", " ") for n in names} and canon not in out.values():
                out[i] = canon
                break
        else:
            if k.replace(" ", "_") in custom_keys:
                out[i] = "custom:" + k.replace(" ", "_")
    return out


def iter_rows(data: bytes, filename: str):
    """Stream rows out of a CSV or XLSX file without loading the whole sheet into lists."""
    if filename.lower().endswith((".xlsx", ".xlsm")):
        from openpyxl import load_workbook

        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        for row in wb.active.iter_rows(values_only=True):
            yield ["" if v is None else str(v).strip() for v in row]
        wb.close()
        return
    for row in csv.reader(io.StringIO(data.decode("utf-8-sig", errors="replace"))):
        yield [c.strip() for c in row]


def email_hash(email: str) -> str:
    return hashlib.sha256(email.strip().lower().encode()).hexdigest()


async def _roster_import(job_id: uuid.UUID) -> None:
    from app.campus.models import CustomField
    from app.campus.storage import decrypt

    async with session_scope() as s:
        job = await s.get(CampusJob, job_id)
        campus = await s.get(Campus, job.campus_id)
        data, filename, by = decrypt(job.blob), job.payload.get("filename", "roster.csv"), job.created_by
        depts = {d.name.lower(): d.id for d in (await s.execute(select(Department).where(Department.campus_id == campus.id))).scalars()}
        progs = (await s.execute(select(Program, Degree).join(Degree, Degree.id == Program.degree_id).where(Program.campus_id == campus.id))).all()
        batches = {(b.program_id, b.admission_year): b for b in (await s.execute(select(Batch).where(Batch.campus_id == campus.id))).scalars()}
        custom_keys = [c.key for c in (await s.execute(select(CustomField).where(CustomField.campus_id == campus.id))).scalars()]
    by_prog: dict[tuple, Program] = {}
    for p, d in progs:
        for name in {d.abbreviation.lower(), d.name.lower(), f"{d.abbreviation} {p.specialisation}".strip().lower()}:
            by_prog[(p.department_id, name)] = p
    scale = campus.score_scale or {}
    max_score = float(scale.get("max") or 0) or None

    rows = iter_rows(data, filename)
    header = next(rows, [])
    cols = _header_map(header, custom_keys)
    errors: list[list] = []
    if "student_id" not in cols.values() or "name" not in cols.values():
        errors.append([1, "header", f"Needs a {campus.student_id_label} column and a name column"])
        await _progress(job_id, 0, 0, imported=0, errors=errors)
        return
    pending: list[dict] = []
    imported = seen = 0
    seen_ids: set[str] = set()

    async def flush():
        nonlocal imported
        if not pending:
            return
        async with session_scope() as s:
            await s.execute(
                text(
                    "INSERT INTO roster_students (campus_id, id, student_id_at_institution, name, college_email_hash, department_id, program_id, batch_id, "
                    "score_value, score_scale, pending_subjects, graduation_year, current_term, custom, search_name, source, updated_by) "
                    "VALUES (:campus_id, :id, :sid, :name, :email_hash, :department_id, :program_id, :batch_id, :score, CAST(:scale AS jsonb), :pending, :gy, :term, "
                    "CAST(:custom AS jsonb), :search, 'roster', :by) "
                    "ON CONFLICT (campus_id, student_id_at_institution) DO UPDATE SET name = EXCLUDED.name, college_email_hash = coalesce(EXCLUDED.college_email_hash, roster_students.college_email_hash), "
                    "department_id = EXCLUDED.department_id, program_id = EXCLUDED.program_id, batch_id = EXCLUDED.batch_id, score_value = EXCLUDED.score_value, "
                    "score_scale = EXCLUDED.score_scale, pending_subjects = EXCLUDED.pending_subjects, graduation_year = EXCLUDED.graduation_year, "
                    "current_term = EXCLUDED.current_term, custom = EXCLUDED.custom, search_name = EXCLUDED.search_name, source = 'roster', updated_by = EXCLUDED.updated_by, updated_at = now()"
                ),
                pending,
            )
        imported += len(pending)
        pending.clear()
        await _progress(job_id, imported)

    import json

    for n, raw in enumerate(rows, start=2):
        if not any(raw):
            continue
        seen += 1
        if seen > MAX_ROWS:
            errors.append([n, "", f"Stopped at {MAX_ROWS:,} rows: split the file"])
            break
        r = {cols[i]: v for i, v in enumerate(raw) if i in cols}
        problems = []
        sid, name = (r.get("student_id") or "").strip()[:60], re.sub(r"<[^>]*>", "", (r.get("name") or "")).strip()[:200]
        if not sid:
            problems.append(("student_id", f"{campus.student_id_label} is empty"))
        elif sid in seen_ids:
            problems.append(("student_id", "duplicate in this file"))
        if not name:
            problems.append(("name", "name is empty"))
        dept_id = depts.get((r.get("department") or "").strip().lower()) if r.get("department") else None
        if r.get("department") and not dept_id:
            problems.append(("department", f"no department called '{r['department']}' (add it in Setup first)"))
        prog = by_prog.get((dept_id, (r.get("degree") or "").strip().lower())) if dept_id and r.get("degree") else None
        if r.get("degree") and dept_id and not prog:
            problems.append(("degree", f"'{r['degree']}' isn't a programme of this department (add it in Setup first)"))
        score = None
        if r.get("score"):
            try:
                score = float(r["score"].replace("%", ""))
                if score < 0 or (max_score and score > max_score):
                    problems.append(("score", f"outside the college's scale (0-{max_score:g})"))
            except ValueError:
                problems.append(("score", "not a number"))
        pend = None
        if r.get("pending_subjects"):
            try:
                pend = int(float(r["pending_subjects"]))
            except ValueError:
                problems.append(("pending_subjects", "not a whole number"))
        def year(key):
            v = (r.get(key) or "").strip()
            if not v:
                return None
            if not re.fullmatch(r"(19|20)\d\d", v[:4]):
                problems.append((key, "not a year"))
                return None
            return int(v[:4])
        adm, gy = year("admission_year"), year("graduation_year")
        term = None
        if r.get("term"):
            m = re.search(r"\d+", r["term"])
            term = int(m.group(0)) if m else None
        email = (r.get("email") or "").strip().lower()
        if email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            problems.append(("email", "not an email address"))
        if problems:
            errors.extend([n, c, msg] for c, msg in problems[: MAX_ERRORS - len(errors)])
            continue
        seen_ids.add(sid)
        batch_id = None
        if prog and (adm or gy):
            dur = int(float(prog.duration_years or 0)) or 3
            adm = adm or (gy - dur)
            key = (prog.id, adm)
            if key not in batches:
                async with session_scope() as s:
                    b = Batch(id=uuid7(), campus_id=campus.id, program_id=prog.id, admission_year=adm, graduation_year=gy or adm + dur)
                    s.add(b)
                batches[key] = b
            batch_id = batches[key].id
            gy = gy or batches[key].graduation_year
        custom = {k.removeprefix("custom:"): v for k, v in r.items() if k.startswith("custom:") and v != ""}
        pending.append({"campus_id": campus.id, "id": uuid7(), "sid": sid, "name": name, "email_hash": email_hash(email) if email else None, "department_id": dept_id,
                        "program_id": prog.id if prog else None, "batch_id": batch_id, "score": score, "scale": json.dumps(scale) if scale else None, "pending": pend,
                        "gy": gy, "term": term, "custom": json.dumps(custom), "search": name.lower(), "by": by})
        if len(pending) >= BATCH:
            await flush()
    await flush()
    await _progress(job_id, imported, seen, imported=imported, rows=seen, errors=errors[:MAX_ERRORS])
    await enqueue(campus.id, "rollup", f"rollup:{campus.id}:{datetime.now(UTC):%Y%m%d%H%M}")


def errors_csv(job: CampusJob) -> str:
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["row", "column", "problem"])
    for e in (job.result or {}).get("errors", []):
        w.writerow(e)
    return out.getvalue()


# ---------- drive eligibility ----------


async def _eligibility(job_id: uuid.UUID) -> None:
    from app.models import CampusDrive

    async with session_scope() as s:
        job = await s.get(CampusJob, job_id)
        drive = await s.get(CampusDrive, uuid.UUID(job.payload["drive_id"]))
        rules = (drive.eligibility or {}).get("rules") or []
        campus_id = job.campus_id
        programs = {p.id: (p, d) for p, d in (await s.execute(select(Program, Degree).join(Degree, Degree.id == Program.degree_id).where(Program.campus_id == campus_id))).all()}
        total = (await s.execute(text("SELECT count(*) FROM roster_students WHERE campus_id = :c"), {"c": campus_id})).scalar_one()
    await _progress(job_id, 0, total)
    last = uuid.UUID(int=0)
    done = 0
    while True:
        async with session_scope() as s:
            rows = (
                await s.execute(
                    text(
                        "SELECT id, department_id, program_id, batch_id, current_term, score_value, pending_subjects, graduation_year, custom "
                        "FROM roster_students WHERE campus_id = :c AND id > :last ORDER BY id LIMIT :n"
                    ),
                    {"c": campus_id, "last": last, "n": BATCH},
                )
            ).all()
            if not rows:
                break
            out = []
            for r in rows:
                p, d = programs.get(r.program_id, (None, None))
                rec = Record(
                    department_id=str(r.department_id) if r.department_id else None, program_id=str(r.program_id) if r.program_id else None,
                    degree_id=str(d.id) if d else None, field_code=p.field_code if p else None, isced_level=d.isced_level if d else None,
                    term=r.current_term, score=float(r.score_value) if r.score_value is not None else None, pending_subjects=r.pending_subjects,
                    graduation_year=r.graduation_year, custom=r.custom or {},
                )
                ok, failed = evaluate(rules, rec)
                out.append({"c": campus_id, "d": drive.id, "r": r.id, "e": ok, "f": failed, "dept": r.department_id, "p": r.program_id, "b": r.batch_id})
            await s.execute(
                text(
                    "INSERT INTO drive_eligibility (campus_id, drive_id, roster_student_id, eligible, failed_rules, department_id, program_id, batch_id, evaluated_at) "
                    "VALUES (:c, :d, :r, :e, :f, :dept, :p, :b, now()) ON CONFLICT (campus_id, drive_id, roster_student_id) DO UPDATE SET "
                    "eligible = EXCLUDED.eligible, failed_rules = EXCLUDED.failed_rules, department_id = EXCLUDED.department_id, program_id = EXCLUDED.program_id, "
                    "batch_id = EXCLUDED.batch_id, evaluated_at = now()"
                ),
                out,
            )
            last = rows[-1].id
        done += len(rows)
        await _progress(job_id, done)
    async with session_scope() as s:
        eligible = (await s.execute(text("SELECT count(*) FROM drive_eligibility WHERE campus_id = :c AND drive_id = :d AND eligible"), {"c": campus_id, "d": drive.id})).scalar_one()
    await _progress(job_id, done, total, evaluated=done, eligible=eligible, rule_ids=[r["id"] for r in rules])
    log.info("campus.eligibility", campus_id=str(campus_id), drive_id=str(drive.id), evaluated=done, eligible=eligible, rule_ids=[r["id"] for r in rules])


# ---------- rollups ----------

ROLLUP_SQL = {
    # metric -> SQL returning (level, ref_id, value) rows for one campus
    "students": """
        SELECT 'campus', '', count(*) FROM roster_students WHERE campus_id = :c
        UNION ALL SELECT 'department', department_id::text, count(*) FROM roster_students WHERE campus_id = :c AND department_id IS NOT NULL GROUP BY department_id
        UNION ALL SELECT 'program', program_id::text, count(*) FROM roster_students WHERE campus_id = :c AND program_id IS NOT NULL GROUP BY program_id
        UNION ALL SELECT 'batch', batch_id::text, count(*) FROM roster_students WHERE campus_id = :c AND batch_id IS NOT NULL GROUP BY batch_id
        UNION ALL SELECT 'degree', p.degree_id::text, count(*) FROM roster_students r JOIN programs p ON p.id = r.program_id WHERE r.campus_id = :c GROUP BY p.degree_id""",
    "on_jobpilot": """
        SELECT 'campus', '', count(*) FROM campus_memberships WHERE campus_id = :c AND kind = 'student' AND status = 'active'
        UNION ALL SELECT 'department', department_id::text, count(*) FROM campus_memberships WHERE campus_id = :c AND kind = 'student' AND status = 'active' AND department_id IS NOT NULL GROUP BY department_id""",
    "sharing": """
        SELECT 'campus', '', count(*) FROM campus_memberships WHERE campus_id = :c AND kind = 'student' AND status = 'active' AND shares_with_college""",
    "pending_students": """
        SELECT 'campus', '', count(*) FROM campus_memberships WHERE campus_id = :c AND kind = 'student' AND status IN ('pending', 'waitlisted')""",
}
ACHIEVEMENT_SQL = """
    SELECT department_id::text, kind, status, coalesce(level, ''), count(*), count(DISTINCT user_id)
    FROM student_achievements WHERE campus_id = :c GROUP BY 1, 2, 3, 4"""
FUNNEL_SQL = """
    SELECT stage, count(DISTINCT user_id) FROM campus_placements WHERE org_id = :c GROUP BY stage"""
ELIGIBLE_SQL = "SELECT count(DISTINCT roster_student_id) FROM drive_eligibility WHERE campus_id = :c AND eligible"


async def rebuild_rollups(campus_id: uuid.UUID) -> dict[tuple, int]:
    values: dict[tuple, int] = {}
    async with session_scope() as s:
        for metric, sql in ROLLUP_SQL.items():
            for level, ref, v in (await s.execute(text(sql), {"c": campus_id})).all():
                values[(level, ref or "", metric)] = int(v)
        for dept, kind, status, level, n, students in (await s.execute(text(ACHIEVEMENT_SQL), {"c": campus_id})).all():
            for lvl, ref in (("campus", ""), ("department", dept or "")):
                if lvl == "department" and not dept:
                    continue
                for key, val in ((f"{kind}_{status}", n), (f"{kind}_all", n)):
                    values[(lvl, ref, key)] = values.get((lvl, ref, key), 0) + val
                if kind == "internship" and status == "verified":
                    values[(lvl, ref, "students_with_verified_internship")] = values.get((lvl, ref, "students_with_verified_internship"), 0) + students
                if kind == "award" and status == "verified" and level in ("national", "international"):
                    values[(lvl, ref, "national_award_winners")] = values.get((lvl, ref, "national_award_winners"), 0) + students
        values[("campus", "", "eligible")] = int((await s.execute(text(ELIGIBLE_SQL), {"c": campus_id})).scalar_one())
        stages = dict((await s.execute(text(FUNNEL_SQL), {"c": campus_id})).all())
        values[("campus", "", "applied")] = sum(v for k, v in stages.items() if k not in ("proposed", "dismissed"))
        values[("campus", "", "shortlisted")] = sum(v for k, v in stages.items() if k in ("shortlisted", "round_1", "technical", "hr", "placed"))
        values[("campus", "", "placed")] = stages.get("placed", 0)
        for level, ref, cap in (await s.execute(text("SELECT level, ref_id::text, capacity FROM capacity_allocations WHERE campus_id = :c"), {"c": campus_id})).all():
            values[(level, "" if level == "campus" else ref, "capacity")] = int(cap)
        await s.execute(text("DELETE FROM campus_rollups WHERE campus_id = :c"), {"c": campus_id})
        if values:
            await s.execute(
                text("INSERT INTO campus_rollups (campus_id, level, ref_id, metric, value, updated_at) VALUES (:c, :l, :r, :m, :v, now())"),
                [{"c": campus_id, "l": k[0], "r": k[1], "m": k[2], "v": v} for k, v in values.items()],
            )
    return values


async def _rollup(job_id: uuid.UUID) -> None:
    async with session_scope() as s:
        campus_id = (await s.get(CampusJob, job_id)).campus_id
    await rebuild_rollups(campus_id)


async def maintenance() -> None:
    """Hourly: next month's audit-log partition exists, and every campus's rollups are at most 15 minutes old."""
    now = datetime.now(UTC)
    async with session_scope() as s:
        for k in (1, 2):
            y, m = divmod(now.month - 1 + k, 12)
            start = now.replace(year=now.year + y, month=m + 1, day=1, hour=0, minute=0, second=0, microsecond=0)
            y2, m2 = divmod(start.month, 12)
            end = start.replace(year=start.year + y2, month=m2 + 1)
            await s.execute(text(f"CREATE TABLE IF NOT EXISTS staff_view_audit_log_{start:%Y%m} PARTITION OF staff_view_audit_log FOR VALUES FROM ('{start:%Y-%m-%d}') TO ('{end:%Y-%m-%d}')"))
        stale = (
            await s.execute(
                text("SELECT c.id FROM campuses c LEFT JOIN (SELECT campus_id, max(updated_at) u FROM campus_rollups GROUP BY campus_id) r ON r.campus_id = c.id WHERE r.u IS NULL OR r.u < now() - interval '15 minutes'")
            )
        ).scalars().all()
    for c in stale:
        await enqueue(c, "rollup", f"rollup:{c}:{now:%Y%m%d%H}{now.minute // 15}")


HANDLERS = {"roster_import": _roster_import, "eligibility": _eligibility, "rollup": _rollup}

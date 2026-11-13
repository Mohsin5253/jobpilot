"""Seed a separate database with 40 lakh students across ~2,000 campuses, to prove Campus v2 scales.

  createdb jobpilot_scale
  DATABASE_URL=postgresql+psycopg://localhost/jobpilot_scale uv run alembic upgrade head
  DATABASE_URL=postgresql+psycopg://localhost/jobpilot_scale uv run python -m scripts.seed_scale [--students 4000000]

Realistic skew: 5 campuses of 50,000-80,000 students (university-sized), the rest log-normal around 500-3,000.
Every student gets a JobPilot account, a membership and a college record; a 5% sample gets 10 achievements each.
Ids are UUIDv7 (time-ordered), generated in SQL. Everything is set-based (INSERT ... SELECT generate_series), so the
whole seed takes minutes, not hours. Never point this at a real database.
"""

import argparse
import asyncio
import math
import random
import time

from sqlalchemy import text

from app.db import engine

UUID7 = (
    "(lpad(to_hex((extract(epoch from clock_timestamp()) * 1000)::bigint), 12, '0') || '7' || substr(md5(random()::text), 1, 3) "
    "|| to_hex(8 + floor(random() * 4)::int) || substr(md5(random()::text), 1, 15))::uuid"
)


def sizes(total: int, campuses: int, seed: int = 7) -> list[int]:
    rng = random.Random(seed)
    big = [rng.randint(50_000, 80_000) for _ in range(5)]
    rest = [max(300, int(rng.lognormvariate(math.log(1400), 0.6))) for _ in range(campuses - 5)]
    scale = (total - sum(big)) / sum(rest)
    rest = [max(200, int(r * scale)) for r in rest]
    out = big + rest
    out[-1] += total - sum(out)
    return out


async def run(sql: str, **params) -> None:
    async with engine.begin() as c:
        await c.execute(text(sql), params)


async def main(total: int, campuses: int) -> None:
    t0 = time.time()
    n = sizes(total, campuses)
    async with engine.begin() as c:
        db = (await c.execute(text("SELECT current_database()"))).scalar_one()
    assert db.endswith("_scale"), f"refusing to seed {db}: use a database whose name ends in _scale"
    async with engine.begin() as c:
        await c.execute(text("DROP TABLE IF EXISTS seed_sizes"))
        await c.execute(text("CREATE TABLE seed_sizes (i int PRIMARY KEY, campus_id uuid, n int, deg uuid)"))
        await c.execute(text("INSERT INTO seed_sizes (i, n) VALUES " + ",".join(f"({i},{v})" for i, v in enumerate(n))))
        await c.execute(text(f"UPDATE seed_sizes SET campus_id = {UUID7}"))
        await c.execute(text("UPDATE seed_sizes SET deg = (SELECT id FROM degrees WHERE abbreviation = 'B.Com.' LIMIT 1)"))
        await c.execute(text("INSERT INTO institutions (id, name) SELECT campus_id, 'Seed institution ' || i FROM seed_sizes"))
        await c.execute(text("INSERT INTO campuses (id, institution_id, name, allowed_email_domains, score_scale) SELECT campus_id, campus_id, 'Seed college ' || i, ARRAY['seed' || i || '.ac.in'], '{\"type\": \"percentage\", \"max\": 100}' FROM seed_sizes"))
        await c.execute(text("INSERT INTO organizations (id, name, slug, invite_code) SELECT campus_id, 'Seed college ' || i, 'seed-' || i, 'S' || lpad(i::text, 6, '0') FROM seed_sizes"))
        # 6 departments, one programme each, 4 batches each (24 batches per campus)
        await c.execute(text(f"INSERT INTO departments (id, campus_id, name) SELECT {UUID7}, s.campus_id, 'Department ' || d FROM seed_sizes s, generate_series(1, 6) d"))
        await c.execute(text(f"INSERT INTO programs (id, campus_id, department_id, degree_id, field_code, duration_years) SELECT {UUID7}, d.campus_id, d.id, s.deg, '0411', 4 FROM departments d JOIN seed_sizes s ON s.campus_id = d.campus_id"))
        await c.execute(text(f"INSERT INTO batches (id, campus_id, program_id, admission_year, graduation_year) SELECT {UUID7}, p.campus_id, p.id, y, y + 4 FROM programs p, generate_series(2022, 2025) y"))
        await c.execute(text("CREATE TABLE seed_slots AS SELECT b.campus_id, b.program_id, p.department_id, b.id AS batch_id, row_number() OVER (PARTITION BY b.campus_id ORDER BY b.id) - 1 AS slot FROM batches b JOIN programs p ON p.id = b.program_id"))
        await c.execute(text("CREATE INDEX ON seed_slots (campus_id, slot)"))
    print(f"structure: {len(n)} campuses, {time.time() - t0:.0f}s", flush=True)

    # Students, in chunks of campuses so each statement stays a few hundred thousand rows.
    done = 0
    order = list(range(len(n)))
    chunk: list[int] = []
    for i in order + [-1]:
        if i >= 0:
            chunk.append(i)
        if chunk and (i < 0 or sum(n[j] for j in chunk) >= 250_000):
            ids = ",".join(str(j) for j in chunk)
            await run(
                f"""
                INSERT INTO users (id, email, password_hash, name, adult_confirmed_at)
                SELECT {UUID7}, 'stu' || s.i || '-' || g || '@seed.example', 'x', 'Student ' || s.i || '-' || g, now()
                FROM seed_sizes s, generate_series(1, s.n) g WHERE s.i IN ({ids})
                """
            )
            await run(
                f"""
                INSERT INTO roster_students (campus_id, id, student_id_at_institution, name, department_id, program_id, batch_id, score_value, score_scale,
                                             pending_subjects, graduation_year, current_term, search_name, claimed_user_id, claimed_at, source)
                SELECT s.campus_id, {UUID7}, 'R' || g, 'Student ' || s.i || '-' || g, sl.department_id, sl.program_id, sl.batch_id, round((40 + random() * 60)::numeric, 1),
                       '{{"type": "percentage", "max": 100}}', (random() * 3)::int, 2026 + (g % 4), 1 + (g % 8), lower('student ' || s.i || '-' || g), u.id, now(), 'roster'
                FROM seed_sizes s CROSS JOIN generate_series(1, s.n) g
                JOIN LATERAL (SELECT * FROM seed_slots x WHERE x.campus_id = s.campus_id AND x.slot = g % 24) sl ON true
                JOIN users u ON u.email = 'stu' || s.i || '-' || g || '@seed.example'
                WHERE s.i IN ({ids})
                """
            )
            await run(
                f"""
                INSERT INTO campus_memberships (campus_id, id, institution_id, user_id, kind, status, department_id, program_id, batch_id, roster_student_id, shares_with_college)
                SELECT r.campus_id, {UUID7}, r.campus_id, r.claimed_user_id, 'student', 'active', r.department_id, r.program_id, r.batch_id, r.id, random() < 0.6
                FROM roster_students r JOIN seed_sizes s ON s.campus_id = r.campus_id WHERE s.i IN ({ids})
                """
            )
            done += sum(n[j] for j in chunk)
            print(f"students: {done:,} / {sum(n):,} ({time.time() - t0:.0f}s)", flush=True)
            chunk = []

    # Achievements: a 5% sample of students, 10 entries each, across the three kinds.
    await run(
        f"""
        INSERT INTO student_achievements (campus_id, id, user_id, kind, sub_type, category, title, organisation, level, position, start_date, status,
                                          shares_with_college, department_id, program_id, batch_id, dedupe_key, created_at)
        SELECT m.campus_id, {UUID7}, m.user_id, (ARRAY['internship', 'role', 'award'])[1 + k % 3], CASE WHEN k % 3 = 0 THEN 'internship' ELSE '' END,
               CASE WHEN k % 3 = 2 THEN 'cultural' ELSE '' END, 'Entry ' || k, 'Org ' || k,
               CASE WHEN k % 3 = 2 THEN (ARRAY['college', 'inter_college', 'state', 'national', 'international'])[1 + k % 5] END,
               CASE WHEN k % 3 = 2 THEN (ARRAY['winner', 'runner_up', 'finalist', 'participant'])[1 + k % 4] END,
               date '2023-01-01' + (k * 37 % 900), (ARRAY['self_reported', 'verified', 'verified', 'rejected'])[1 + k % 4],
               m.shares_with_college, m.department_id, m.program_id, m.batch_id, 'seed|' || k, now() - (k || ' days')::interval
        FROM campus_memberships m, generate_series(1, 10) k
        WHERE m.kind = 'student' AND abs(hashtext(m.id::text)) % 20 = 0
        """
    )
    async with engine.begin() as c:
        for t in ("users", "roster_students", "campus_memberships", "student_achievements"):
            await c.execute(text(f"ANALYZE {t}"))
        counts = {t: (await c.execute(text(f"SELECT count(*) FROM {t}"))).scalar_one() for t in ("campuses", "roster_students", "campus_memberships", "student_achievements")}
    print(f"done in {time.time() - t0:.0f}s: {counts}", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--students", type=int, default=4_000_000)
    ap.add_argument("--campuses", type=int, default=2000)
    a = ap.parse_args()
    asyncio.run(main(a.students, a.campuses))

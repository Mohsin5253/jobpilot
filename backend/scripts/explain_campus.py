"""EXPLAIN ANALYZE the typical staff queries on the seeded 40-lakh database, under row-level security exactly as the API
runs them (SET LOCAL ROLE jobpilot_campus + the app.* settings). Fails if a query scans a whole large table or more
than one partition, and prints timings.

  DATABASE_URL=postgresql+psycopg://localhost/jobpilot_scale uv run python -m scripts.explain_campus
"""

import asyncio
import json
import re
import sys

from sqlalchemy import text

from app.db import engine

QUERIES = {
    "tpo: student list, first page": ("tpo", "SELECT * FROM roster_students WHERE campus_id = :c ORDER BY created_at DESC, id DESC LIMIT 51"),
    "tpo: student list, deep page (keyset)": ("tpo", "SELECT * FROM roster_students WHERE campus_id = :c AND (created_at, id) < (:ts, :rid) ORDER BY created_at DESC, id DESC LIMIT 51"),
    "hod: own department": ("hod", "SELECT * FROM roster_students WHERE campus_id = :c AND department_id = :d ORDER BY created_at DESC, id DESC LIMIT 51"),
    "faculty: own batch": ("faculty", "SELECT * FROM roster_students WHERE campus_id = :c AND batch_id = :b ORDER BY created_at DESC, id DESC LIMIT 51"),
    "tpo: name search (trigram)": ("tpo", "SELECT * FROM roster_students WHERE campus_id = :c AND search_name LIKE '%student 0-4242%' LIMIT 51"),
    "tpo: student detail": ("tpo", "SELECT * FROM roster_students WHERE campus_id = :c AND id = :rid"),
    "hod: verification queue": ("hod", "SELECT * FROM student_achievements WHERE campus_id = :c AND status = 'self_reported' ORDER BY created_at DESC, id DESC LIMIT 51"),
    "tpo: student's entries": ("tpo", "SELECT * FROM student_achievements WHERE campus_id = :c AND user_id = :u"),
    "tpo: dashboard (rollups)": ("tpo", "SELECT * FROM campus_rollups WHERE campus_id = :c"),
    "student: own entries": ("student", "SELECT * FROM student_achievements WHERE user_id = :u"),
}
LARGE = ("roster_students", "student_achievements", "campus_memberships")


async def plan(sql: str, role: str, p: dict) -> tuple[list[str], float]:
    async with engine.begin() as c:
        await c.execute(text("SET LOCAL ROLE jobpilot_campus"))
        settings = {"app.campus_role": role, "app.user_id": str(p["u"]), "app.campus_ids": "{" + str(p["c"]) + "}",
                    "app.dept_ids": "{" + str(p["d"]) + "}", "app.program_ids": "{}", "app.batch_ids": "{" + str(p["b"]) + "}"}
        for k, v in settings.items():
            await c.execute(text("SELECT set_config(:k, :v, true)"), {"k": k, "v": v})
        rows = (await c.execute(text("EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT) " + sql), p)).scalars().all()
    ms = float(re.search(r"Execution Time: ([\d.]+) ms", rows[-1]).group(1))
    return rows, ms


async def main() -> int:
    async with engine.begin() as c:
        big = (await c.execute(text("SELECT campus_id, n FROM seed_sizes ORDER BY n DESC LIMIT 1"))).first()
        small = (await c.execute(text("SELECT campus_id, n FROM seed_sizes ORDER BY n LIMIT 1"))).first()
    out, ok = [], True
    for label, (cid, n) in (("largest campus", big), ("smallest campus", small)):
        async with engine.begin() as c:
            off = 40000 if n > 40000 else 0  # a deep keyset page on the big campus
            r = (await c.execute(text("SELECT id, created_at, department_id, batch_id, claimed_user_id FROM roster_students WHERE campus_id = :c ORDER BY created_at DESC, id DESC OFFSET :o LIMIT 1"), {"c": cid, "o": off})).first()
            u = (await c.execute(text("SELECT user_id FROM student_achievements WHERE campus_id = :c LIMIT 1"), {"c": cid})).scalar() or r.claimed_user_id
        p = {"c": cid, "d": r.department_id, "b": r.batch_id, "rid": r.id, "ts": r.created_at, "u": u}
        for name, (role, sql) in QUERIES.items():
            lines, ms = await plan(sql, role, p)
            body = "\n".join(lines)
            seq_large = [ln.strip() for ln in lines if "Seq Scan" in ln and any(t in ln for t in LARGE)]
            parts = {m for m in re.findall(r"on (\w+_p\d\d)", body)}
            bad = (bool(seq_large) and n > 5000) or (len({re.sub(r"_p\d\d$", "", x) for x in parts}) and len(parts) > len({re.sub(r"_p\d\d$", "", x) for x in parts}) and "student: own" not in name)
            ok &= not bad
            out.append({"campus": f"{label} ({n:,} students)", "query": name, "ms": ms, "partitions": sorted(parts), "index": "Index" in body or "Bitmap" in body, "ok": not bad})
    w = max(len(o["query"]) for o in out)
    for o in out:
        print(f"{'OK ' if o['ok'] else 'BAD'} {o['campus']:<32} {o['query']:<{w}} {o['ms']:>8.2f} ms  {'index' if o['index'] else 'scan':<5} {','.join(o['partitions'])}")
    with open("evals/reports/campus-explain.json", "w") as f:
        json.dump(out, f, indent=2, default=str)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

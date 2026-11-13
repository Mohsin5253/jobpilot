"""Load test for Campus v2 on the seeded scale database (no extra tools: asyncio + httpx).

  # 1. the API on the scale DB, without the embedded worker or rate limits, several processes:
  DATABASE_URL=postgresql+psycopg://localhost/jobpilot_scale EMBEDDED_WORKER=false RATE_LIMITS_ENABLED=false \
      uv run uvicorn app.main:app --port 8010 --workers 8
  # 2. this script (creates staff tokens for the biggest campuses and student tokens directly in the DB):
  DATABASE_URL=postgresql+psycopg://localhost/jobpilot_scale uv run python -m scripts.loadtest_campus --staff 200 --students 1000 --seconds 60

Staff virtual users loop over: student list (first page, then a keyset page), a student's detail, the dashboard,
drives, and the verification queue. Student virtual users add achievements. Reports p50 / p95 / p99 per endpoint,
errors and throughput, and writes evals/reports/campus-loadtest.json.
"""

import argparse
import asyncio
import json
import random
import statistics
import time
import uuid
from collections import defaultdict

from sqlalchemy import text

from app.campus.access import mint_staff_token
from app.campus.ids import uuid7
from app.db import engine
from app.models import User
from app.security import create_token


class Conn:
    """A minimal keep-alive HTTP/1.1 client on asyncio streams: one connection per virtual user. (httpx's async pool
    slows down badly with hundreds of connections, which would make the client the bottleneck being measured.)"""

    def __init__(self, host: str, port: int):
        self.host, self.port, self.r, self.w = host, port, None, None

    async def request(self, method: str, path: str, headers: dict, body: bytes | None = None) -> tuple[int, bytes]:
        for attempt in range(2):
            try:
                if self.w is None:
                    self.r, self.w = await asyncio.open_connection(self.host, self.port)
                head = f"{method} {path} HTTP/1.1\r\nHost: {self.host}\r\n" + "".join(f"{k}: {v}\r\n" for k, v in headers.items())
                if body is not None:
                    head += f"content-type: application/json\r\ncontent-length: {len(body)}\r\n"
                self.w.write((head + "\r\n").encode() + (body or b""))
                await self.w.drain()
                status_line = await self.r.readline()
                if not status_line:
                    raise ConnectionError("closed")
                status = int(status_line.split()[1])
                length, chunked = 0, False
                while True:
                    line = await self.r.readline()
                    if line in (b"\r\n", b""):
                        break
                    k, _, v = line.decode().partition(":")
                    if k.lower() == "content-length":
                        length = int(v)
                    elif k.lower() == "transfer-encoding" and "chunked" in v.lower():
                        chunked = True
                if chunked:
                    data = b""
                    while True:
                        size = int((await self.r.readline()).strip(), 16)
                        if size == 0:
                            await self.r.readline()
                            break
                        data += await self.r.readexactly(size)
                        await self.r.readline()
                else:
                    data = await self.r.readexactly(length) if length else b""
                return status, data
            except (ConnectionError, OSError, asyncio.IncompleteReadError, ValueError):
                self.w = None
                if attempt:
                    raise
        raise ConnectionError("unreachable")


async def prepare(n_campuses: int, n_students: int) -> tuple[list[dict], list[dict]]:
    staff, students = [], []
    async with engine.begin() as c:
        campuses = (await c.execute(text("SELECT campus_id, n FROM seed_sizes ORDER BY n DESC LIMIT :k"), {"k": n_campuses})).all()
        for cid, _ in campuses:
            email = f"tpo-{str(cid)[-8:]}@loadtest.example"
            uid = (await c.execute(text("SELECT id FROM users WHERE email = :e"), {"e": email})).scalar()
            if uid is None:
                uid = uuid7()
                await c.execute(text("INSERT INTO users (id, email, password_hash, name, adult_confirmed_at) VALUES (:i, :e, 'x', 'Load TPO', now())"), {"i": uid, "e": email})
                await c.execute(text("INSERT INTO campus_memberships (campus_id, id, user_id, kind, role, status, email_verified) VALUES (:c, :i, :u, 'staff', 'tpo', 'active', true)"),
                                {"c": cid, "i": uuid7(), "u": uid})
            mid = (await c.execute(text("SELECT id FROM campus_memberships WHERE campus_id = :c AND user_id = :u"), {"c": cid, "u": uid})).scalar_one()
            u = User(id=uid, email=email, token_version=0)
            staff.append({"campus": str(cid), "auth": create_token(uid, 0), "staff": mint_staff_token(u, mid, cid, "tpo", "active")})
        rows = (await c.execute(text("SELECT m.user_id FROM campus_memberships m TABLESAMPLE SYSTEM (1) WHERE m.kind = 'student' LIMIT :n"), {"n": n_students})).scalars().all()
        students = [{"auth": create_token(u, 0)} for u in rows]
    return staff, students


async def shard(base: str, n_staff: int, n_students: int, seconds: int, campuses: int) -> dict:
    staff, students = await prepare(campuses, max(1, n_students))
    lat: dict[str, list[float]] = defaultdict(list)
    errors: dict[str, int] = defaultdict(int)
    stop = time.monotonic() + seconds

    from urllib.parse import urlparse

    u = urlparse(base)
    host, port = u.hostname, u.port or 80
    if True:

        async def call(conn: Conn, name: str, method: str, url: str, headers: dict, json_body: dict | None = None):
            t = time.perf_counter()
            try:
                status, data = await conn.request(method, url, headers, json.dumps(json_body).encode() if json_body is not None else None)
                ok = status < 400
            except (ConnectionError, OSError, asyncio.IncompleteReadError):
                status, data, ok = 0, b"", False
            lat[name].append((time.perf_counter() - t) * 1000)
            if not ok:
                errors[name] += 1
            return status, data

        async def staff_user(i: int):
            s = staff[i % len(staff)]
            h = {"authorization": f"Bearer {s['auth']}", "x-staff-token": s["staff"]}
            conn = Conn(host, port)
            while time.monotonic() < stop:
                st, data = await call(conn, "students: first page", "GET", "/api/campus/staff/students?limit=50", h)
                if st == 200:
                    page = json.loads(data)
                    if page["items"]:
                        if page["next_cursor"]:
                            await call(conn, "students: keyset page", "GET", f"/api/campus/staff/students?limit=50&cursor={page['next_cursor']}", h)
                        await call(conn, "student detail", "GET", f"/api/campus/staff/students/{random.choice(page['items'])['id']}", h)
                await call(conn, "dashboard", "GET", "/api/campus/staff/dashboard", h)
                await call(conn, "drives (eligibility counts)", "GET", "/api/campus/staff/drives", h)
                await call(conn, "verification queue", "GET", "/api/campus/staff/achievements?limit=50", h)

        async def student_user(i: int):
            h = {"authorization": f"Bearer {students[i % len(students)]['auth']}"}
            conn = Conn(host, port)
            while time.monotonic() < stop:
                body = {"kind": "award", "title": f"Load event {uuid.uuid4().hex[:10]}", "organisation": "Load fest", "category": "cultural", "level": "college",
                        "position": "participant", "start_date": "2025-03-01"}
                await call(conn, "add achievement", "POST", "/api/campus-profile/achievements", h, body)
                await asyncio.sleep(random.uniform(0.5, 2.0))  # a person filling a form, not a tight loop

        t0 = time.monotonic()
        await asyncio.gather(*(staff_user(i) for i in range(n_staff)), *(student_user(i) for i in range(n_students)))
        elapsed = time.monotonic() - t0
    return {"lat": dict(lat), "errors": dict(errors), "elapsed": elapsed}


def _run_shard(args) -> dict:
    return asyncio.run(shard(*args))


def main(base: str, n_staff: int, n_students: int, seconds: int, campuses: int, procs: int) -> None:
    """Split the virtual users across `procs` client processes (one Python process can drive only a few hundred
    requests a second, so a single client would measure itself, not the server) and merge their latencies."""
    from multiprocessing import get_context

    parts = [(base, n_staff // procs + (i < n_staff % procs), n_students // procs + (i < n_students % procs), seconds, campuses) for i in range(procs)]
    with get_context("spawn").Pool(procs) as pool:
        results = pool.map(_run_shard, parts)
    lat: dict[str, list[float]] = defaultdict(list)
    errors: dict[str, int] = defaultdict(int)
    for r in results:
        for k, v in r["lat"].items():
            lat[k] += v
        for k, v in r["errors"].items():
            errors[k] += v
    elapsed = max(r["elapsed"] for r in results)

    def pct(xs, p):
        xs = sorted(xs)
        return xs[min(len(xs) - 1, int(p / 100 * len(xs)))] if xs else None

    report = {"base": base, "staff_vus": n_staff, "student_vus": n_students, "client_processes": procs, "seconds": round(elapsed, 1), "endpoints": {}}
    total = sum(len(v) for v in lat.values())
    print(f"{'endpoint':<30}{'requests':>10}{'p50 ms':>9}{'p95 ms':>9}{'p99 ms':>9}{'errors':>8}")
    for name, xs in sorted(lat.items()):
        report["endpoints"][name] = {"requests": len(xs), "p50": round(statistics.median(xs), 1), "p95": round(pct(xs, 95), 1), "p99": round(pct(xs, 99), 1), "errors": errors[name]}
        e = report["endpoints"][name]
        print(f"{name:<30}{e['requests']:>10}{e['p50']:>9}{e['p95']:>9}{e['p99']:>9}{e['errors']:>8}")
    report["throughput_rps"] = round(total / elapsed, 1)
    report["error_rate"] = round(sum(errors.values()) / max(1, total), 4)
    print(f"throughput {report['throughput_rps']} req/s, error rate {report['error_rate']:.2%}")
    with open(f"evals/reports/campus-loadtest-{n_staff}s-{n_students}st.json", "w") as f:
        json.dump(report, f, indent=2)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8010")
    ap.add_argument("--staff", type=int, default=200)
    ap.add_argument("--students", type=int, default=1000)
    ap.add_argument("--seconds", type=int, default=60)
    ap.add_argument("--campuses", type=int, default=20)
    ap.add_argument("--procs", type=int, default=4)
    a = ap.parse_args()
    main(a.base, a.staff, a.students, a.seconds, a.campuses, a.procs)

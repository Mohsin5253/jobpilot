"""Load test the API with many signed-in users browsing at once.

Creates N throwaway accounts straight in the database (copies of the showcase account, like demo visitors,
so each has real matches and drafts), then has C of them at a time load the dashboard, job list, drafts
and profile through the HTTP API, and reports throughput and p50 / p95 / p99 latency per endpoint.
The accounts are deleted afterwards (and expire within the hour anyway).

  uv run python -m scripts.load_test                  # 200 users, 50 concurrent, against localhost:8000
  uv run python -m scripts.load_test 1000 100 https://api.example.com
"""

import asyncio
import statistics
import sys
import time
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import delete, select

from app.db import SessionLocal
from app.models import User
from app.security import create_token
from app.services.demo import create_demo_user

ENDPOINTS = ["/api/stats/overview", "/api/matches?limit=20", "/api/drafts", "/api/profile", "/api/notifications"]
TAG = "loadtest-"


async def seed(n: int) -> list[str]:
    tokens = []
    for _ in range(n):
        async with SessionLocal() as s:
            user = await create_demo_user(s)
            user = await s.get(User, user.id)
            user.email = TAG + user.email
            user.expires_at = datetime.now(UTC) + timedelta(hours=1)
            await s.commit()
            tokens.append(create_token(user.id, user.token_version, ttl_hours=1))
    return tokens


async def cleanup() -> int:
    async with SessionLocal() as s:
        ids = (await s.execute(select(User.id).where(User.email.startswith(TAG)))).scalars().all()
        await s.execute(delete(User).where(User.id.in_(ids)))
        await s.commit()
        return len(ids)


async def main(n: int, concurrency: int, base: str) -> None:
    print(f"Seeding {n} accounts…")
    t0 = time.perf_counter()
    tokens = await seed(n)
    print(f"  done in {time.perf_counter() - t0:.1f}s")
    timings: dict[str, list[float]] = {e: [] for e in ENDPOINTS}
    errors = 0
    sem = asyncio.Semaphore(concurrency)

    async with httpx.AsyncClient(base_url=base, timeout=30, limits=httpx.Limits(max_connections=concurrency)) as client:

        async def session(token: str) -> None:
            nonlocal errors
            async with sem:
                for path in ENDPOINTS:  # one dashboard visit
                    start = time.perf_counter()
                    r = await client.get(path, headers={"authorization": f"Bearer {token}"})
                    timings[path].append((time.perf_counter() - start) * 1000)
                    errors += r.status_code >= 400

        await client.get("/health")
        t0 = time.perf_counter()
        await asyncio.gather(*(session(t) for t in tokens))
        wall = time.perf_counter() - t0

    total = sum(len(v) for v in timings.values())
    print(f"\n{total:,} requests from {n:,} users ({concurrency} at a time) in {wall:.1f}s → {total / wall:,.0f} req/s, {errors} errors\n")
    print(f"{'endpoint':<26} {'p50':>8} {'p95':>8} {'p99':>8}")
    for path, ms in timings.items():
        ms.sort()
        q = statistics.quantiles(ms, n=100) if len(ms) > 1 else [ms[0]] * 99
        print(f"{path.split('?')[0]:<26} {q[49]:>6.0f}ms {q[94]:>6.0f}ms {q[98]:>6.0f}ms")
    print(f"\nRemoved {await cleanup()} load-test accounts.")


if __name__ == "__main__":
    args = sys.argv[1:]
    asyncio.run(main(int(args[0]) if args else 200, int(args[1]) if len(args) > 1 else 50, args[2] if len(args) > 2 else "http://localhost:8000"))

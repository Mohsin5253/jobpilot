# Campus v2: scale results

Measured 13 Nov 2026 on one laptop: Apple Silicon, 10 cores, 16 GB RAM, PostgreSQL 18 (Homebrew, default settings,
`shared_buffers` 128 MB). The API, Postgres and the load client all ran on the same machine. Production numbers will
differ: see "What this means for production".

## The data

`scripts/seed_scale.py` filled a separate database (`jobpilot_scale`) in 577 s:

| | Rows |
|---|---|
| Campuses | 2,000. The 5 largest have 60,611–71,329 students; the rest are log-normal around 500–3,000; the smallest has 334 |
| Student accounts | 40,00,000 (plus the reference data) |
| Memberships | 40,00,000 (60% sharing with their college) |
| College records (roster) | 40,00,000 + 1,00,000 from the import test |
| Achievements | 19,98,020 (a 5% sample of students with 10 entries each) |
| Database size | 6.9 GB |

Large tables are hash-partitioned 32 ways on `campus_id`, with UUIDv7 ids. Every query below runs under row-level
security, exactly as the API runs it (`SET LOCAL ROLE jobpilot_campus` plus the `app.*` settings).

## Queries: index scans on one partition (`scripts/explain_campus.py`)

| Query | Largest campus (71,329) | Smallest (334) |
|---|---|---|
| TPO: student list, first page | 0.12 ms | 0.22 ms |
| TPO: student list, keyset page 800 deep | 0.14 ms | 0.25 ms |
| HOD: own department | 0.52 ms | 0.07 ms |
| Faculty: own batch | 0.28 ms | 0.03 ms |
| TPO: name search (trigram) | 17.98 ms | 0.17 ms |
| TPO: one student's record | 0.27 ms | 0.40 ms |
| HOD: verification queue | 9.07 ms | 0.48 ms |
| TPO: one student's entries | 0.40 ms | 0.37 ms |
| Dashboard (pre-aggregated rollups) | 0.48 ms | 0.07 ms |
| Student: own entries (no campus in the query: all 32 partitions, each by index) | 5.47 ms | 4.26 ms |

- No query does a sequential scan of a large table.
- Every staff query touches exactly one partition.
- The first run measured the student list at **27 ms**: its index put department and batch before `created_at`, so Postgres sorted the whole campus. Migration `0031` adds indexes shaped like each list (campus, [department | batch | status], created_at DESC, id DESC), which brought it to **0.12 ms**.

## Background jobs

| Job | Size | Time | Target |
|---|---|---|---|
| Drive eligibility (3 rules, in batches of 5,000) | 71,329 students | **3.3 s** (11,910 eligible) | 50,000 in < 2 min |
| Roster import (CSV, streamed, upserts of 5,000) | 1,00,000 rows, 8.8 MB | **8.5 s**, 0 errors | 1 lakh rows in one upload |
| Dashboard rollups (full rebuild) | 71,329 students | **0.47 s** | refreshed every 15 min and after imports |

## API under load (`scripts/loadtest_campus.py`)

The API ran with 6 processes, a pool of 8 + 4 connections each, no background worker and no rate limits.

- **Virtual staff** loop with no pause: student list, a keyset page, a student's detail, the dashboard, drives, then the verification queue. They're spread over the 20 largest campuses.
- **Virtual students** add an achievement every 0.5–2 s.

| Concurrency | Throughput | List / detail p95 | Dashboard p95 | Add entry p95 | Errors |
|---|---|---|---|---|---|
| 40 staff + 150 students | 617 req/s | 147–338 ms | 158 ms | 351 ms | 0 |
| 80 staff + 300 students | 549 req/s | 491–674 ms | 539 ms | 656 ms | 0 |
| 200 staff + 1,000 students | 595 req/s | 2.1–3.3 s | 3.2 s | 3.3 s | 0 |

**What's saturated.** At these levels the API processes use about 5 of the 10 cores (about 8 ms of Python CPU per request) and Postgres about 2.5. The machine is CPU-bound at about 600 requests a second. Queries stay at milliseconds; the time above them is queueing for CPU.

**Fixed along the way:**
1. **A pool deadlock.** Every request held its first database connection for its whole lifetime while campus code opened more connections from the same pool. Under load that gave a **27% error rate and 30 s timeouts**. `current_user` now ends its transaction once the user is loaded.
2. **Row-level security set-up cost.** The role switch and the six `app.*` settings now go in **one** statement, down from seven.
3. **Staff scope cache.** Each staff member's scope is cached for 30 s, keyed by account version, so deactivation still applies on the next request.
4. **The load client was the bottleneck.** A single httpx client on one core capped the test at about 235 req/s. It now uses a minimal keep-alive client across several processes.

## The spec's targets, honestly

| Target | Result |
|---|---|
| 40 lakh students, no technical cap | ✅ seeded and queried; no limit in the schema or code below 40 lakh |
| Index scans proven with EXPLAIN ANALYZE on the 40-lakh DB | ✅ every typical staff query, largest and smallest campus |
| Eligibility over 50,000 in < 2 min | ✅ 71,329 in 3.3 s |
| 1 lakh-row roster upload | ✅ 8.5 s |
| p95 < 300 ms (lists / detail), < 500 ms (dashboard), no errors | ✅ dashboard and errors. ⚠️ Lists and detail: 147–338 ms at 190 concurrent busy users on one laptop |
| 2,000 concurrent staff + 20,000 concurrent students | ❌ not run. One laptop can't host 22,000 connections alongside the API and Postgres; it needs the staging environment you chose not to pay for yet. The numbers above give the sizing |

## What this means for production

- **Throughput:** about 600 req/s took about 5 API cores, so about **120 req/s per API core**.
- **Real staff** don't hammer: assume one request every 5 s. 2,000 concurrent staff is about 400 req/s.
- **Students** adding an entry about once a minute: 20,000 students is about 330 req/s.
- **Peak:** about **730 req/s**, which is about **6–7 API cores** (for example 3–4 Render instances of 2 vCPU, horizontally) plus a Postgres instance with 4+ vCPU and enough RAM for the indexes, about 3 GB at 40 lakh.
- **When to add more:**
  - add a read replica for dashboards when their p95 passes 500 ms in production;
  - add PgBouncer when total pool connections (instances × (`DB_POOL_SIZE` + `DB_MAX_OVERFLOW`)) approach the database's `max_connections`.

**To reproduce:**
```
createdb jobpilot_scale
DATABASE_URL=postgresql+psycopg://localhost/jobpilot_scale uv run alembic upgrade head
DATABASE_URL=postgresql+psycopg://localhost/jobpilot_scale uv run python -m scripts.seed_scale
DATABASE_URL=postgresql+psycopg://localhost/jobpilot_scale uv run python -m scripts.explain_campus
DATABASE_URL=postgresql+psycopg://localhost/jobpilot_scale EMBEDDED_WORKER=false RATE_LIMITS_ENABLED=false uv run uvicorn app.main:app --port 8010 --workers 6
DATABASE_URL=postgresql+psycopg://localhost/jobpilot_scale uv run python -m scripts.loadtest_campus --staff 40 --students 150 --procs 2
```

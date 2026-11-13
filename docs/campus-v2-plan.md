# Campus v2: audit and migration plan

> **Status, 13 Nov 2026: built.** You asked for no paid services, so the free alternatives in §14 replace every paid
> item in §8.5 and §11. The AISHE 2015-16 tables you provided are imported (§12.1–12.2). Measured results are in
> `docs/campus-load-test.md`.

Written 13 Nov 2026, before any schema change, as the spec asks. Sections 1–3 describe what exists today and what's
missing. Sections 4–9 are the target design. Section 10 is the migration plan. Sections 11–12 list what needs your
approval and the questions only you can answer.

## 0. Summary

Today's campus mode works for a few colleges of a few hundred students each. It doesn't meet this spec in four ways.

1. **It won't scale.**
   - The college dashboard loads every student of a college into memory and checks eligibility for each one, inside the web request.
   - It looks up consent one student at a time.
   - The consent rule in the database runs a join for every row it filters.
   - There's no pagination, and no pre-computed totals.
   - IDs are random (UUIDv4), and nothing is partitioned.
   - Production runs on Render's **free** Postgres plan, which can't hold 40 lakh students.
2. **Staff verification is weak.**
   - Staff get access the moment they enter the staff code; there's no approval step.
   - A college domain is checked only if the TPO has set one, so Gmail addresses aren't rejected.
   - **Account emails are never verified**, by OTP or by link.
   - The code isn't rotated automatically and doesn't lock after repeated failures; only a per-user rate limit exists.
   - Deactivating someone doesn't end their existing sessions.
3. **It assumes engineering.**
   - The checks use `cgpa`, `branch` and `backlogs`.
   - The drive parser has a hardcoded list of branches (CSE, IT, ECE, EEE, MECH, CIVIL, AIDS, AIML, CHEM, MCA).
   - Round templates are coding-first.
   - The audit found these terms in about 40 files: `cgpa` in 17, `branch` in 15, `backlog` in 9.
   - There's no table of fields, degrees or grading scales.
4. **Students can't record achievements.** There are no internships, positions of responsibility or awards with proof and staff verification.

What is already right and stays:
- consent-gated visibility enforced by Postgres;
- an audit row for each staff read of student-level data;
- staff codes stored only as hashes;
- TPOs appointed only by JobPilot or another TPO;
- AI match proposals that staff approve.

## 1. Current schema

| Table | Holds | Keys and indexes | Notes |
|---|---|---|---|
| `organizations` | one college | UUIDv4 PK, unique `slug`, `invite_code` | `domain` (one optional staff domain), `staff_code_hash`, `staff_code_set_at`. No institution/university level, no type, city, state or website. |
| `org_members` | anyone linked to a college | UUIDv4 PK, **unique `user_id`**, index `org_id` | `role` = student / tpo / hod / teacher / officer; `department` is a free-text string. A user can belong to **one** college, with one role. No status (pending/active), no programme or batch. |
| `profiles.academics` (JSONB) | the student's own CGPA, branch, backlogs, grad year | none | **Typed in by the student**: nothing is from the college, and nothing is read-only. |
| `campus_drives` | a drive | UUIDv4 PK, index `org_id` | `eligibility` JSONB with fixed keys `min_cgpa`, `branches`, `max_backlogs`, `grad_years`. `rounds` JSONB. |
| `drive_statuses` | a student's progress in a drive | unique (drive, user) | No `campus_id` column: scoping needs a join. |
| `campus_placements` | AI proposal → staff decision → rounds | unique (org, user, job), index (org, stage) | Has an RLS consent policy. |
| `audit_events` | staff reads, joins, role changes | index `created_at` | Not partitioned; no `campus_id` column (it sits in `subject` as text). |
| `consents` | per-purpose consent ledger | — | The purpose `college_share` gates staff visibility. |

**RLS today** (migrations 0019 and 0024):
- Each of `profiles`, `job_matches`, `drive_statuses` and `campus_placements` has a restrictive SELECT policy: rows are visible when `app.viewer_org` is unset, or when `user_id IN (SELECT m.user_id FROM org_members m JOIN consents c … )`.
- Officer reads switch to the `jobpilot_officer` role with `SET LOCAL ROLE` and set `app.viewer_org` with `set_config(..., true)`.

The rule is correct. But the `IN (subquery with join)` is evaluated against `org_members` and `consents` for every query, the spec forbids that, and it can't use a campus-leading index.

## 2. Current limits

| Area | Today | Breaks at |
|---|---|---|
| College dashboard (`GET /api/college`) | loads every student and profile, calls `has(consent)` per student, runs eligibility for every drive × every student, all in the request | about 2,000–5,000 students per college (one query per student plus O(students × drives) Python) |
| Student list (`GET /api/college/students`) | `COUNT(*)` + full list, no pagination | about 10,000 students |
| Totals | `COUNT(*)` on each page load | lakhs of rows per page |
| Search | none | — |
| Bulk onboarding | none (students join with the invite code themselves) | — |
| Long work | the agent worker already uses a Postgres queue (`agent_runs`, `SKIP LOCKED`) for agent runs; campus work runs inside requests | — |
| Files | ledger offer letters are stored **encrypted inside Postgres** (`doc_enc`) | proof files at scale |
| Database | `render.yaml` (in use): **free** Postgres (Render deletes free databases after 30 days); `render.production.yaml`: basic-1gb | the free plan can't hold this data |
| Connections | 5 + overflow per process, no pooler | a few hundred concurrent staff |
| Staff caps | only in **pricing copy** ("1 TPO + 3 staff", "HOD + 5 faculty"); no cap in code | — |
| Student plan limits | in pricing copy only; the FAQ already says they're soft | — |

## 3. Current auth flow for staff

1. A user signs up (email + password, or Google). **The email is never verified.**
2. They open `/college`, enter the staff code, and pick HOD or teacher plus a department (free text).
3. The server compares the HMAC of the code, and requires `email` to end with `org.domain` only if the TPO set one.
4. They're `ACTIVE` immediately, with full access to their scope. There's no pending state.
5. The checks are `staff_member()` (a `role IN staff roles` lookup) plus `need(member, perm)`. RLS adds the consent filter.
6. Removing staff deletes the membership. Their JWT stays valid until it expires, and each request re-reads the membership, so access ends then. There's no session revocation and no audit of logins.

Students and staff share one `org_members` row per user (unique `user_id`). A student can't also be staff, but nothing makes the switch explicit.

## 4. Gaps against the spec

| Spec item | Today | Gap |
|---|---|---|
| 1. 40 lakh students, tenant-keyed tables, UUIDv7/bigint, partitions | UUIDv4, no partitions, no institution level | new tables (§5) |
| 1. RLS with `SET LOCAL app.user_id / campus_id / role`, no per-row subqueries | one setting, a subquery policy | new policies on denormalised columns (§6) |
| 1. Keyset pagination, pre-aggregated totals, background eligibility, trigram search | none | §8 |
| 1. Roster import of 1 lakh rows, invites that students claim | none | §8.4 |
| 1. Pooling, job queue, object storage, rate limits per campus, read replica | partly (queue for agents) | §8.5, paid parts need approval |
| 1. Seed 40 lakh, load test, documented results | none | §9 |
| 2. Unlimited staff on every plan | copy says 3 / 5 staff on Pilot and Department | copy change, needs approval (§11) |
| 3. Verified staff only | code only, no email verification, no pending state, no free-mail block, no lockout, no session revocation, no login audit | §7 |
| 3. Students never reach the staff portal | `/campus` **is the student page** today; staff use `/college` | route move (§7.5) |
| 4. Student achievements with proof and verification | none | §5.4, §8.6 |
| 4B. Any field or degree, native grading scales, rules as data | engineering-only | §5.3 |
| 4C. Setup wizard, programmes, batches, capacity tree, staff assignments, drill-down | free-text department | §5.2, §8.3 |
| 4C.6. College records vs JobPilot data | everything is gated by consent today | wording change, needs approval (§11) |
| AISHE reference tables (`ref_programme`, `ref_broad_discipline_group_category`) | **not in this repository or on this computer** | I need the files (§12) |

## 5. Target schema

All new large tables use **UUIDv7** primary keys. They're time-ordered and index-friendly, and generated in the app (Python 3.13 has no `uuid7`, so a 20-line helper or the `uuid6` package).
- Every campus table leads with `campus_id`.
- Monetary and score values are numeric. Free text is plain text with length limits.

### 5.1 Tenancy

```
institutions(id, name, type: university|college_group|standalone, country_code, website, created_at)
campuses(id, institution_id, name, native_name, city, state, country_code, type, aishe_code NULL,
         website, allowed_email_domains text[], student_id_label, pending_subjects_label NULL,
         score_scale_default jsonb, locale, timezone, plan, created_at)
departments(id, campus_id, name, native_name, created_at)            -- index (campus_id, name)
```

Existing `organizations` rows become a `campuses` row, plus an `institutions` row for each standalone college, keeping the same id (§10).

### 5.2 Structure, capacity and assignments

```
programs(id, campus_id, department_id, degree_id, field_id, specialisation, duration_terms, term_type,
         intake_per_year, created_at)                                -- "department_degree_programs"
batches(id, campus_id, program_id, admission_year, graduation_year, current_term, term_override, created_at)
capacity_allocations(id, campus_id, level: campus|degree|department|program|batch, ref_id, capacity,
                     updated_by, updated_at)                         -- unique (campus_id, level, ref_id)
capacity_history(id, campus_id, level, ref_id, old, new, by, at)      -- written by trigger
staff_assignments(id, campus_id, staff_user_id, role, department_id NULL, program_id NULL, batch_id NULL,
                  status: pending|approved|revoked, requested_at, approved_by, approved_at)
```

The capacity rule "children never exceed their parent" is checked in one transaction when an allocation is saved (a
`SELECT … FOR UPDATE` on the parent). A full level puts new joins on `waitlist` and notifies the HOD and TPO; it never
blocks.

### 5.3 Fields, degrees, scales and eligibility rules (every discipline)

```
fields(code PK, level: broad|narrow|detailed, parent_code, name, names jsonb)   -- ISCED-F 2013
degrees(id, name, abbreviation, isced_level 3..8, typical_duration_terms, term_type, country_code NULL,
        custom_campus_id NULL)                                        -- seeded: India + common international
campus_fields(id, campus_id, field_code, specialisation, native_name)  -- a college's own specialisations
academic_records(campus_id, membership_id, student_id_at_institution, program_id, batch_id,
                 score_value numeric, score_scale jsonb {type: cgpa|gpa|percentage|division|letter|pass_fail, max},
                 pending_subjects int NULL, graduation_year, source: roster|staff, updated_by, updated_at)
custom_fields(id, campus_id, key, label, type: yes_no|number|text)    -- "valid nursing registration"
custom_values(campus_id, membership_id, field_id, value)
eligibility_rules(id, campus_id, drive_id, rule jsonb, position)      -- the rule builder's rows
```

Rule types:
- `field_in`, `degree_in`, `level_in` and `term_in`;
- `score_gte`, always compared in the campus's own scale and never converted;
- `pending_subjects_lte` and `graduation_year_in`;
- `custom_yes` or `custom_number_gte`;
- `category_in` and `gender_in`, allowed only when the campus turns them on, with a legal-basis note.

The rule evaluator is pure Python, logs every rule id it applies, and replaces `services/campus.eligibility`.

The ISCED-F 2013 taxonomy (11 broad, 29 narrow, about 80 detailed fields) and ISCED 2011 levels are seeded from the
published UNESCO lists. Indian programmes are mapped from the AISHE tables once you provide them (§12).

### 5.4 Student achievements

```
student_achievements(id uuid7, campus_id, membership_id, user_id, kind: internship|role|award,
    sub_type, category, title, organisation, level NULL, position NULL, mode NULL,
    start_date, end_date NULL, ongoing bool, stipend_inr NULL, stipend_private bool default true,
    description text (≤ 2,000, plain), proof_object_key NULL, proof_mime NULL, proof_sha256 NULL,
    status: self_reported|verified|rejected, reject_reason NULL, verified_by NULL, verified_at NULL,
    verifier_flags text[], shares_with_college bool,          -- denormalised for RLS (§6)
    department_id, program_id, batch_id,                       -- denormalised for RLS
    dedupe_key text, created_at, updated_at)
```

- **Partitioning:** `PARTITION BY HASH (campus_id)` with 32 partitions; primary key `(campus_id, id)`.
- **Indexes:**
  - `(campus_id, status, kind, created_at, id)` for queues with keyset paging;
  - `(campus_id, department_id, kind, level)` for dashboards;
  - unique `(campus_id, user_id, dedupe_key)`.
- **Who can write what:**
  - students may write only the listed fields, enforced by an API allowlist schema and column privileges for the app role;
  - academic records are never writable by students;
  - editing a verified entry resets it to self-reported, done by trigger so no code path can skip it.

### 5.5 Memberships and audit

```
campus_memberships(id uuid7, campus_id, institution_id, user_id, kind: student|staff,
    role NULL (staff: tpo|principal|hod|faculty|coordinator|university_admin), status: invited|pending|active|waitlisted|deactivated,
    department_id NULL, program_id NULL, batch_id NULL, shares_with_college bool, invite_id NULL,
    session_epoch int, created_at, updated_at)
staff_view_audit_log(id, campus_id, actor_user_id, action: login|view_student|approve|export|verify|role_change,
    subject_user_id NULL, detail jsonb, at)
roster_invites(id, campus_id, student_id_at_institution, name, college_email_hash, program_id, batch_id,
    academic fields…, claimed_by NULL, claimed_at NULL, created_at)
```

- **`campus_memberships`:**
  - hash-partitioned on `campus_id` (32 partitions);
  - unique `(campus_id, user_id, kind)`, so a user can be both a student and staff only through two separate rows, which the UI makes explicit;
  - indexes `(campus_id, kind, status, department_id, batch_id, id)` and `(user_id)`.
- **`staff_view_audit_log`:** range-partitioned **by month** on `at`, so old months can be dropped under the retention rule.
- **Roster invites:** the college email is stored only as a hash until it's claimed, and an invite never shows a name before consent.

Students are no longer limited to one college in the schema. The UI still allows one active campus per student.

## 6. Row-level security that stays fast

Each request runs in a transaction that sets:

```
SET LOCAL app.user_id = '<uuid>';
SET LOCAL app.campus_id = '<uuid>';
SET LOCAL app.role = 'tpo' | 'principal' | 'hod' | 'faculty' | 'coordinator' | 'university_admin' | 'student';
SET LOCAL app.dept_ids = '{…}';    -- from approved staff_assignments, resolved once per request
SET LOCAL app.program_ids = '{…}';
SET LOCAL app.batch_ids = '{…}';
SET LOCAL app.campus_ids = '{…}';  -- university admins only
```

Policies compare columns to these settings only. There are no subqueries and no functions that read other tables.

```sql
-- campus-scoped tables (example: student_achievements, for the staff role)
USING (
  campus_id = current_setting('app.campus_id')::uuid
  AND shares_with_college                                       -- JobPilot data needs consent
  AND ( current_setting('app.role') IN ('tpo','principal')
     OR (current_setting('app.role') IN ('hod','coordinator') AND department_id = ANY (current_setting('app.dept_ids')::uuid[]))
     OR (current_setting('app.role') = 'faculty' AND (program_id = ANY (current_setting('app.program_ids')::uuid[])
                                                       OR batch_id = ANY (current_setting('app.batch_ids')::uuid[]))) )
)
-- students: only their own rows
USING (user_id = current_setting('app.user_id')::uuid)
```

- **Consent is denormalised:**
  - the `shares_with_college` flag lives on `campus_memberships` and `student_achievements`;
  - a trigger on `consents` keeps it current;
  - withdrawal takes effect in the same transaction, faster than the promised 24 hours.
- **College records** (academic records, roster data): visible to staff in scope **without** consent, under the 4C.6 rule. This needs your wording approval first (§11).
- **Pending and deactivated staff** get no `app.role`, so every policy returns no rows.
- **The app's database role** is `NOBYPASSRLS`, with `FORCE ROW LEVEL SECURITY` on every campus table.
- **Proof:** a test runs `EXPLAIN (ANALYZE, BUFFERS)` for the five typical staff queries on the seeded 40-lakh database and asserts index or bitmap scans on the right partition, with no sequential scan of a large table.

## 7. Staff verification and the staff-only portal

### 7.1 Joining (all steps required)

1. **Staff code:**
   - HMAC-hashed, shown once, rotatable, with an optional expiry;
   - **locked for 15 minutes after 5 failed tries** per user and per IP, and for the campus after 50 failures in an hour, which alerts the TPO.
2. **Institutional email:**
   - a 6-digit OTP sent to an address whose domain is in `campuses.allowed_email_domains`;
   - personal domains are always rejected, using the Scam Shield `FREE_MAIL` list plus rediffmail, yahoo.co.in and similar;
   - the TPO edits the allowed domains in Settings;
   - this also adds `users.email_verified_at`, which the whole app is missing today.
3. **Approval:** the membership starts as `pending` with no data access. The TPO or Principal approves it, and the HOD or TPO approves each department, programme or batch assignment. Staff can't grant themselves access.
4. **AISHE match (optional, once per campus):**
   - when the campus is created, the AISHE record (name, city, state, website) is matched;
   - if its website domain equals the email domain, the allowed domain is pre-filled;
   - a mismatch goes to manual review and never blocks on its own.

### 7.2 Enforcement, server-side, in this order

1. The JWT carries `campus_role`, `membership_status`, `campus_id` and `session_epoch`.
2. **Next.js middleware** on `/campus/**` redirects anyone without `membership_status=active` and a staff role to the student app.
3. **A FastAPI dependency** on `/api/campus/staff/**` checks the same claims, then compares `session_epoch` with the database value (cached for 30 s).
4. **Deactivation:**
   - increments `session_epoch`, so old tokens get **401** on the next call, at most 30 s later;
   - the cache entry is evicted immediately on the instance that handles the deactivation.
5. **RLS** repeats the rule (§6).
6. **Audit:** every staff login, every view of an individual student, every approval and every export is written to `staff_view_audit_log`.
7. **2FA** (email OTP at login) is required for TPO and Principal accounts. It's optional for other staff.

### 7.3 Students and staff

A student account never holds a staff role at the same campus. If a student's email later passes staff verification:
- they get a **separate** staff membership, which still needs TPO approval;
- the app shows a "Switch to staff portal" control, and the student data and the staff portal never mix in one session.

### 7.4 Rate limits

On top of today's per-user limits:
- per-campus limits on login, OTP, code tries, exports and roster imports;
- a per-user limit on the student list and search endpoints.

### 7.5 Routes (needs your OK, §11)

The spec puts the staff portal at `/campus/**`, but `/campus` is the **student** page today. The plan:
- Move the student page to `/campus-profile` (Campus profile tab: drives timeline plus achievements).
- Move the staff portal from `/college` to `/campus/**`, with redirects from the old paths for 90 days.
- Group the staff APIs under `/api/campus/staff/**` (from `/api/college/**`), keeping the old paths as aliases for one release.

## 8. Building it to scale

### 8.1 Reads

- **Pagination:** keyset paging everywhere, e.g. `WHERE (created_at, id) < ($1, $2) ORDER BY created_at DESC, id DESC LIMIT 50`, with an opaque cursor.
- **Search:** `pg_trgm` GIN indexes on `(campus_id, lower(name))` and `student_id_at_institution`, always filtered by `campus_id` first. The `pg_trgm` extension must be enabled on Render.
- **Caching:** dashboard responses are cached for 60 s per scope and invalidated when the rollup refreshes.

### 8.2 Pre-aggregated dashboards

- **Table:** `campus_rollups(campus_id, level, ref_id, metric, value, updated_at)`. Levels are campus, degree, department, program and batch. Metrics include students, capacity, eligible, applied, shortlisted, placed, internships, verified internships, roles and awards by level, and PPOs.
- **Refresh:** incremental through triggers for counts (membership and achievement inserts and status changes), plus a full rebuild every 15 minutes per campus as a queue job.
- **Display:** the UI shows "updated X min ago".
- **Correctness:** a test checks that every parent equals the sum of its children on seeded data.

### 8.3 Setup wizard

The steps:
1. Find the college (AISHE search, or "add my college", which goes to manual review).
2. Choose the degrees offered.
3. Create departments, each linked to its degrees, which makes the programmes.
4. Create batches.
5. Set capacity: total, then per degree, then per department or programme, then per batch.

Capacity is shown as a tree of allocated, used and remaining, with "split evenly" and "use intake numbers" helpers.

### 8.4 Roster import (1 lakh rows)

1. The CSV or XLSX is streamed (`csv` or `openpyxl` read-only mode) into the job queue, never parsed inside the request.
2. Each row is validated against the campus's labels and scales.
3. Rows are upserted 5,000 at a time into `roster_invites` and `academic_records`, keyed by `(campus_id, student_id_at_institution)`.
4. Progress shows in the UI.
5. The result is an error-report file (row, column, problem).

Imported rows create **invites, not accounts**. A student claims one by verifying the college email by OTP, and their name isn't shown to staff as a JobPilot user until they consent.

### 8.5 Jobs and infrastructure

- **Job queue:** reuse the Postgres queue pattern the agent worker already uses (`FOR UPDATE SKIP LOCKED`) as a general `campus_jobs` table. Kinds are import, eligibility, matching, rollup and notify. Each job has an idempotency key, retries with backoff, and progress. No new paid service is needed for this.
- **Eligibility:**
  - batches of 5,000 students, run as a job, never inside a request;
  - results go into `drive_eligibility(campus_id, drive_id, membership_id, eligible, rule_ids)`;
  - the target is 50,000 students in under 2 minutes.
- **Pooling:**
  - **PgBouncer** in transaction mode, as a Render private service (Render Postgres has no built-in pooler as far as I know: please confirm on your plan);
  - the API pool is sized to it;
  - `SET LOCAL` works in transaction mode because every setting is per transaction.
- **Object storage:** proof files and offer letters go to an S3-compatible bucket (Cloudflare R2 or S3), using signed upload and download URLs, with only metadata in Postgres. This is a **paid service: needs your approval**. Until it's approved, files under 5 MB stay encrypted in Postgres, as the ledger does today, which works but doesn't scale.
- **Read replica:** switch it on when dashboard p95 goes over 500 ms, or when primary CPU stays above 60% at peak. A Render read replica needs a paid plan, so it **needs approval**.
- **Database size** (rough, to be measured with the seed):
  - 40 lakh memberships: about 1–1.5 GB with indexes;
  - academic records: about 1 GB;
  - achievements for a 10% sample at 10 each (40 lakh rows): about 2–3 GB;
  - audit log: grows with use.
  
  The **free plan can't hold this**: it needs a paid Render Postgres instance with tens of GB of disk and at least 4 GB RAM for the indexes to stay in memory. **Needs approval** (§11).

### 8.6 Achievements

- **Validation:**
  - an allowlist schema per kind, so a `cgpa` field returns 400;
  - plain text only (HTML stripped through `safety.untrusted.clean`);
  - length limits;
  - `end ≥ start`, and no future dates except "ongoing";
  - a duplicate key of kind + normalised event + date + position.
- **Proof files:**
  - PDF, JPG or PNG only, checked by magic bytes and not just the extension, up to 5 MB;
  - images are re-encoded with Pillow to strip EXIF and GPS;
  - a virus scan, which needs ClamAV as a service (**paid or self-hosted, needs approval**). Until then, type checks and re-encoding only.
- **Verifier on offer letters:** offer letters run through Verifier and Scam Shield. A fee request, personal email or lookalike flags the entry for staff, and the student sees the warning plus the cybercrime.gov.in / 1930 note.
- **Proof page:** verified entries appear as "Verified by \<college\>" only if the student turns that on.
- **AI match proposals:** verified entries are used as evidence. Self-reported ones are always labelled as self-reported wherever they appear.

### 8.7 Every field

- **Rounds:** round templates are data per field (aptitude, GD, case study, written test, technical or subject interview, coding, clinical or practical, portfolio review, audition, teaching demo, HR, medical, document verification). "Coding" appears only where the role needs it.
- **Matcher evals:** gold cases for at least 15 fields with non-tech job descriptions and resumes: sales, nursing, law, teaching, design, finance, hospitality, agriculture, government, pharmacy, accounting (CA articleship), civil site work, journalism, HR and hotel management. Accuracy is reported per field, and each field must meet the same threshold in the eval gate.
- **Hardcoded terms:** a grep test fails the build if campus code contains hardcoded branch names (CSE/ECE/MECH…), "CGPA/10" or "backlog" outside the label tables.

## 9. Proving it scales

- `scripts/seed_scale.py`: 40,00,000 students across about 2,000 campuses, in `COPY` batches.
  - The skew follows a Zipf-like curve: 5 campuses above 50,000 students, most between 500 and 3,000.
  - Achievements for a 10% sample, 10 each.
  - Deterministic, so it can be rerun.
- `loadtest/` (k6):
  - 2,000 concurrent staff on the dashboard, student lists, drive eligibility and approvals;
  - 20,000 concurrent students adding achievements.
  - Targets: list and detail p95 under 300 ms, dashboard under 500 ms, 0 errors, and an eligibility job over 50,000 students in under 2 minutes.
- **Where it runs:** a seeded 40-lakh database plus 2,000 to 20,000 virtual users can't run meaningfully on this laptop or on the free Render plan. The EXPLAIN tests and the eligibility timing can run locally on the seeded database. The load test needs a staging copy of the paid production setup, and its results go in `docs/campus-load-test.md`. **Needs approval** for the staging cost.

## 10. Migration plan

Each step is its own migration that can be deployed and rolled back. None of them runs on production data without your OK.

1. **Additive tables:**
   - `institutions`, `campuses` (backfilled from `organizations` with the **same ids**), `departments` (from the distinct free-text `org_members.department` values per org);
   - `fields`, `degrees`, `programs`, `batches`, `capacity_*`, `staff_assignments`, `academic_records`, `custom_*`;
   - `student_achievements` and `campus_memberships`, both partitioned;
   - `staff_view_audit_log`, partitioned by month;
   - `roster_invites`, `campus_jobs`, `campus_rollups`, `drive_eligibility`, `eligibility_rules`.
2. **Backfill memberships:**
   - students keep `active`;
   - for existing staff, **decision needed**: keep them `active` (less disruption) or set them to `pending` until the TPO re-approves them (closer to the spec);
   - `shares_with_college` is copied from `consents`.
3. **Backfill academics:**
   - each `profiles.academics` (student-typed) becomes `academic_records` with `source=student_legacy`, shown as "self-reported, not from the college" until a roster import replaces it;
   - `cgpa` becomes `score_value` on a 10-point CGPA scale **only where the campus confirms that scale**, otherwise left unscaled for review;
   - `backlogs` becomes `pending_subjects`;
   - `branch` maps to a department and programme by name match, with review for anything unmatched.
4. **Drives:** each `campus_drives.eligibility` becomes `eligibility_rules` rows (min_cgpa → score_gte on the campus scale, branches → department_in, and so on).
5. **Dual-write:** for one release, both the old and new tables are written. Reads move to the new tables behind a flag.
6. **Switch reads**, then the new RLS policies and the role changes, then the route moves.
7. **Drop the old columns** a release later. Nothing is deleted until you approve.

## 11. Needs your approval before I build it

1. **Paid infrastructure:**
   - a paid Render Postgres instance large enough for 40 lakh rows;
   - PgBouncer as a private service;
   - object storage (R2 or S3);
   - a read replica, later;
   - ClamAV, optional;
   - a staging environment for the load test.
2. **Pricing copy, "Unlimited staff" on every plan.** The proposed diff in `frontend/lib/campus-pricing.ts`:
   ```diff
   - note: `Up to ${CAMPUS_PILOT_STUDENTS} students · 1 TPO + 3 staff`,
   + note: `Up to ${CAMPUS_PILOT_STUDENTS} students · unlimited staff`,
   - note: `One department, up to ${CAMPUS_DEPARTMENT_STUDENTS} students · HOD + 5 faculty`,
   + note: `One department, up to ${CAMPUS_DEPARTMENT_STUDENTS} students · unlimited staff`,
   ```
   The home page campus section is checked for the same claims.
3. **Who sees what: the two kinds of student data (4C.6).** Proposed new wording.
   - **Campus pricing FAQ, "Can staff see every student's data?":**
     > Two kinds of data, two rules. College records (name, roll number, degree, department, batch, score and pending subjects) come from your college and are visible to authorised staff for the students in their scope. Everything a student creates in JobPilot (applications, resume, matches, internships, roles, awards and proof files) is shown to staff by name only if that student chooses to share it with the college; otherwise staff see only totals. The database enforces both rules, and every staff view is written to an audit log.
   - **Trust page:**
     > If you join your college's workspace, your college's own records about you (name, roll number, programme, batch, score) are visible to the placement staff responsible for you. What you create in JobPilot (applications, resume, matches, internships, roles, awards) is shown to them by name only if you choose to share it; otherwise they see only totals. Both rules are enforced by the database itself, and every staff view is logged.
   - **Consent text for `college_share`:**
     > Share what I create in JobPilot (applications, matches, internships, roles, awards and proof) with my college's placement staff, by name.
   
     This changes a consent purpose's wording, so it needs a new notice version, and students re-confirm it the next time they open Settings.
4. **Routes:** move the student page to `/campus-profile` and the staff portal to `/campus/**` (§7.5).
5. **Existing staff:** keep them active, or require TPO re-approval (§10.2).
6. **Production migrations:** run steps 1–7 of §10 on production data.

## 12. Questions for you

1. **AISHE files:** the spec refers to AISHE reference tables (`ref_programme`, 201 programmes; `ref_broad_discipline_group_category`, 35 groups; a year folder). They aren't in this repository or on this computer. Where are they? Until I have them, programmes are mapped by hand to ISCED for the common Indian degrees, with a note that the AISHE mapping is pending.
2. **AISHE college list (2015–16):** do you have the college directory file for the setup wizard search, or should I build "add my college" with manual review only for now?
3. **Countries:** the spec says to ask before launching outside India. Should foreign campuses be possible in the data model now but turned off in the product until you say so? (Recommended.)
4. **Grading scale conversion:** confirm that nothing converts between scales unless a college uploads its own official formula. (That's what the spec says. I'm confirming because today's code assumes CGPA out of 10.)
5. **2FA for TPO and Principal:** email OTP is the simplest option. Do you want TOTP apps as well?

## 13. Delivery order once approved

1. Tenancy, fields, degrees, scales, programmes and batches, with the backfill (§10.1–3). Rules as data, plus the grep test.
2. Staff verification: email OTP, pending approval, lockout, session epoch, 2FA, the staff-only middleware, RLS with `SET LOCAL`, the audit log, and the access tests.
3. Student achievements: API, RLS, proof handling, Verifier on offer letters, the verification queue, and the Campus profile tab.
4. Setup wizard, capacity tree, staff assignments, the drill-down dashboard with rollups, and keyset tables.
5. Roster import, the job queue, background eligibility, and search.
6. Per-field Matcher evals, and round templates per field.
7. Seed and EXPLAIN tests locally, then the load test on staging. Results go in `docs/campus-load-test.md`.
8. Wording changes, after approval.


## 14. What was built, with free alternatives

| Spec item | Paid option | Free alternative used |
|---|---|---|
| A database big enough for 40 lakh | larger Render Postgres | Designed and proven locally on a seeded 40-lakh database (`scripts/seed_scale.py`, `docs/campus-load-test.md`). Production keeps its current database until real usage needs more: the schema, indexes and partitions are the same at any size. |
| Connection pooling | PgBouncer service | A per-process pool sized to the database's connection limit (`DB_POOL_SIZE`, `DB_MAX_OVERFLOW`). Every campus setting is `SET LOCAL` (per transaction), so the app works unchanged behind PgBouncer or Supabase's / Neon's free poolers later. |
| Object storage | S3 / R2 | Proof files encrypted (Fernet, key outside the DB) in Postgres, at most 5 MB each, behind a storage interface (`app/campus/storage.py`) that can switch to S3/R2 later. Served via 10-minute signed links that are also checked against row-level security. |
| Virus scanning | ClamAV | Magic-byte type checks (PDF, JPG, PNG only); PDFs with JavaScript, launch actions, embedded files or XFA are refused; images are decoded and re-encoded (drops EXIF, GPS and anything hidden after the image). |
| Job queue | Redis / SQS | A Postgres queue (`campus_jobs`, `FOR UPDATE SKIP LOCKED`) with idempotency keys, retries with backoff, and progress; run by the existing worker every 5 s. |
| Read replica | Render replica | Pre-aggregated `campus_rollups` (rebuilt every 15 minutes and after imports), so dashboards never count rows on a page load. A replica is worth it once dashboard p95 passes 500 ms in production. |
| Load test | k6 Cloud | `scripts/loadtest_campus.py` (asyncio + httpx, nothing to install). |

**Decisions taken** (each reversible):
- **Existing staff stay active.** They were admitted under v1's rules; new staff go through verification and approval.
- **Routes:**
  - the student page moved to `/campus-profile`;
  - the staff portal is `/campus/**`, with `/college` redirecting to it;
  - staff portal pages require a staff session, checked by the middleware and by the API.
- **Public wording:** pricing ("unlimited staff"), the campus FAQ, the Trust page and the `college_share` consent text are changed in code and **not deployed**, waiting for your approval of the diff. The notice version is bumped to `2026-11-b`, so students re-confirm.
- **Foreign campuses:**
  - countries, degrees, scales and labels are data, so a foreign university works in the data model, and the tests prove it with a GPA-4 master's;
  - compliance settings (DPDP for India) are not yet per country;
  - launching outside India still waits for you.
- **AISHE:**
  - the 2015-16 directory (54,214 institutions) has no website or email domain, so allowed staff domains are always entered by the TPO and never pre-filled;
  - a college not found in it is added by JobPilot with status `review`.

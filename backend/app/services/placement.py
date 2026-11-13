"""The placement cell: staff roles, the student pipeline, and AI match proposals that staff approve.

Roles (one per college member)
- TPO (training & placement officer): the whole college. Manages staff and codes, posts jobs, approves proposals,
  moves students through rounds. Assigned by JobPilot or promoted by another TPO, never self-selected.
- HOD: their department's students. Posts jobs, approves proposals, moves students through rounds.
- Teacher: their department's students, read-only plus feedback notes.
Staff join with the college's staff code (stored only as an HMAC-SHA256 hash, shown once when issued) and, when the
college sets one, an email on its domain. Students join with the separate student invite code.

What staff can see: aggregates cover every student; anything about one student (name, applications, pipeline) only
for students who chose to share their progress with the college. Postgres row-level security enforces that inside
officer reads (campus_v2.officer_scope), and the app checks again.

AI proposals use a two-stage funnel, like large-scale recommenders:
1. Retrieval: nearest students to the job by embedding (pgvector), within scope, top 20.
2. Re-ranking: an evidence-checked fit review per student (requirement by requirement, quoting the resume), blended
   with semantic and skill-family overlap.
3. Guardrails: seniority (intern vs multi-year roles) and the student's chosen tracks.
Staff decisions on proposals are the ground truth for precision@5, shown on the dashboard.
"""

import asyncio
import hashlib
import hmac
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.config import settings
from app.logging import log
from app.models import CampusPlacement, Job, JobMatch, Notification, Organization, OrgMember, Profile, Stage, User
from app.schemas import Preferences, ResumeData
from app.services.consent import has
from app.services.events import publish

STAFF_ROLES = ("tpo", "hod", "teacher")
ROLE_LABEL = {"tpo": "Training & Placement Officer", "hod": "Head of Department", "teacher": "Faculty"}
PERMS = {
    "tpo": {"view", "approve", "move", "post_job", "manage_staff", "feedback", "drives"},
    "hod": {"view", "approve", "move", "post_job", "feedback", "drives"},
    "teacher": {"view", "feedback"},
}
PIPELINE = ["proposed", "shortlisted", "round_1", "technical", "hr", "placed"]
CLOSED = ["rejected", "dismissed", "withdrawn"]
STAGE_LABEL = {
    "proposed": "AI proposed", "shortlisted": "Shortlisted", "round_1": "Round 1", "technical": "Technical round",
    "hr": "HR round", "placed": "Placed", "rejected": "Rejected", "dismissed": "Not a fit", "withdrawn": "Withdrawn",
}
PROPOSE_MIN = 60.0  # minimum fit (0-100) for an AI proposal
RETRIEVE_K = 20  # students retrieved per job in stage 1
PROPOSE_MAX = 12  # proposals per job


def role_of(member: OrgMember) -> str:
    return "tpo" if member.role == "officer" else member.role


def can(member: OrgMember, perm: str) -> bool:
    return perm in PERMS.get(role_of(member), set())


# ---------- staff codes ----------


def hash_code(code: str) -> str:
    """Keyed hash of a join code: a leaked database doesn't reveal working codes."""
    norm = "".join(code.split()).upper()
    return hmac.new(settings.jwt_secret.encode(), norm.encode(), hashlib.sha256).hexdigest()


def new_staff_code() -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I
    return "STAFF-" + "-".join("".join(secrets.choice(alphabet) for _ in range(4)) for _ in range(3))


async def org_for_staff_code(session, code: str) -> Organization | None:
    h = hash_code(code)
    for org in (await session.execute(select(Organization).where(Organization.staff_code_hash.is_not(None)))).scalars():
        if hmac.compare_digest(org.staff_code_hash or "", h):
            return org
    return None


def email_allowed(org: Organization, email: str) -> bool:
    if not org.domain:
        return True
    d = org.domain.lower().lstrip("@")
    host = email.lower().rsplit("@", 1)[-1]
    return host == d or host.endswith("." + d)


# ---------- scope ----------


_GENERIC = {"engineering", "engg", "eng", "department", "dept", "of", "and", "the", "in", "studies", "school", "faculty"}


def _dept_words(s: str) -> set[str]:
    """v1 department text as its distinctive words (v2 scopes by department ids, not names)."""
    import re

    return {w for w in re.findall(r"[a-z0-9]+", (s or "").lower()) if w not in _GENERIC}


def in_department(member: OrgMember, academics: dict | None) -> bool:
    """TPOs see everyone; HODs and teachers with a department see students of that department ("Mechanical" is
    "Mechanical Engineering": same distinctive words, generic ones like 'engineering' ignored)."""
    if role_of(member) == "tpo" or not member.department.strip():
        return True
    a, b = _dept_words(member.department), _dept_words((academics or {}).get("branch", ""))
    return bool(a and b) and (a <= b or b <= a)


async def staff_ids(session, org_id) -> list[uuid.UUID]:
    return list((await session.execute(select(OrgMember.user_id).where(OrgMember.org_id == org_id, OrgMember.role.in_([*STAFF_ROLES, "officer"])))).scalars())


async def publish_staff(session, org_id, kind: str, **data) -> None:
    """Live update to every staff member's open dashboard."""
    for uid in await staff_ids(session, org_id):
        await publish(session, uid, kind, **data)


async def sharing_students(session, org_id) -> list[tuple[User, Profile]]:
    """Students of the college who share their progress (the only ones staff may see one by one)."""
    rows = (
        await session.execute(
            select(User, Profile).join(OrgMember, OrgMember.user_id == User.id).join(Profile, Profile.user_id == User.id).where(OrgMember.org_id == org_id, OrgMember.role == "student")
        )
    ).all()
    return [(u, p) for u, p in rows if await has(session, u.id, "college_share")]


# ---------- the pipeline ----------


def _hist(p: CampusPlacement, stage: str, by: uuid.UUID | None, note: str = "") -> None:
    p.history = [*(p.history or []), {"stage": stage, "at": datetime.now(UTC).isoformat(), "by": str(by) if by else "ai", "note": note[:300]}]


async def _tell_student(session, p: CampusPlacement, title: str, body: str) -> None:
    session.add(Notification(user_id=p.user_id, kind="campus", title=title[:300], body=body[:1000]))
    await publish(session, p.user_id, "campus_update", placement_id=str(p.id), stage=p.stage)


async def decide(session, p: CampusPlacement, member: OrgMember, approve: bool, note: str = "") -> CampusPlacement:
    if p.stage != "proposed":
        raise ValueError("Already decided")
    p.stage = "shortlisted" if approve else "dismissed"
    p.decided_by, p.decided_at = member.user_id, datetime.now(UTC)
    if note:
        p.feedback = note[:2000]
    _hist(p, p.stage, member.user_id, note)
    if approve:
        # The student's own tracker gets the job too, so tailoring and applying work as usual.
        if p.job_id:
            m = (await session.execute(select(JobMatch).where(JobMatch.user_id == p.user_id, JobMatch.job_id == p.job_id))).scalar_one_or_none()
            if m is None:
                session.add(JobMatch(user_id=p.user_id, job_id=p.job_id, score=p.match_score or 0, semantic_score=0, skill_score=0, strengths=(p.reasoning or {}).get("strengths", []), gaps=(p.reasoning or {}).get("gaps", []), explanation=(p.reasoning or {}).get("explanation", ""), stage=Stage.shortlisted))
            elif m.stage == Stage.found:
                m.stage = Stage.shortlisted
        await _tell_student(session, p, f"Your placement cell shortlisted you: {p.title} at {p.company}", note or "Open Campus to see the next steps.")
    await publish_staff(session, p.org_id, "campus_update", placement_id=str(p.id), stage=p.stage)
    return p


async def move(session, p: CampusPlacement, member: OrgMember, stage: str, note: str = "") -> CampusPlacement:
    if stage not in PIPELINE[1:] + CLOSED:
        raise ValueError("Unknown stage")
    if p.stage == "proposed":
        raise ValueError("Approve the proposal first")
    p.stage = stage
    if note:
        p.feedback = note[:2000]
    _hist(p, stage, member.user_id, note)
    if p.job_id:
        m = (await session.execute(select(JobMatch).where(JobMatch.user_id == p.user_id, JobMatch.job_id == p.job_id))).scalar_one_or_none()
        if m is not None:
            if stage in ("round_1", "technical", "hr"):
                m.outcome, m.stage = "interview", Stage.interview
            elif stage == "placed":
                m.outcome, m.stage = "offer", Stage.offer
            elif stage == "rejected":
                m.outcome, m.stage = "rejected", Stage.rejected
            m.outcome_at = datetime.now(UTC)
    await _tell_student(session, p, f"{p.company}: {STAGE_LABEL[stage]}", note or f"{p.title}: your placement cell moved you to {STAGE_LABEL[stage].lower()}.")
    await publish_staff(session, p.org_id, "campus_update", placement_id=str(p.id), stage=stage)
    return p


# ---------- AI proposals: the two-stage funnel ----------


def _guardrails(job: Job, prefs: Preferences) -> tuple[float, list[str]]:
    from app.agents.matcher import level_factor

    notes = []
    f = level_factor(job.title, job.description or "")
    if f < 1:
        notes.append("Seniority above intern / fresher level")
    if job.track and prefs.tracks and job.track not in prefs.tracks:
        f *= 0.4
        notes.append(f"Student isn't looking for {job.track.replace('_', '-')} roles")
    return f, notes


async def campus_evidence(campus_id, user_ids: list) -> dict:
    """Internships, roles and awards of sharing students (rejected ones left out), each labelled verified or
    self-reported: verified entries count as evidence; self-reported ones are always marked as such."""
    from sqlalchemy import text as _text

    from app.db import session_scope

    if not user_ids:
        return {}
    async with session_scope() as s:
        rows = (
            await s.execute(
                _text("SELECT user_id, kind, sub_type, category, title, organisation, level, position, status FROM student_achievements "
                      "WHERE campus_id = :c AND user_id = ANY(:u) AND shares_with_college AND status <> 'rejected' ORDER BY status DESC, start_date DESC NULLS LAST"),
                {"c": campus_id, "u": list(user_ids)},
            )
        ).all()
    out: dict = {}
    for r in rows:
        out.setdefault(r.user_id, []).append({"kind": r.kind, "type": r.sub_type or r.category, "title": r.title, "organisation": r.organisation, "level": r.level,
                                              "position": r.position, "status": r.status})
    return {k: v[:12] for k, v in out.items()}


def _with_campus(resume_json: str, entries: list[dict]) -> str:
    import json as _json

    if not entries:
        return resume_json
    data = _json.loads(resume_json)
    data["college_record_entries"] = entries  # status: "verified" by the college, or "self_reported"
    return _json.dumps(data)[:12000]


async def propose_for_job(session, org: Organization, job: Job, member: OrgMember | None, ctx_user: uuid.UUID | None) -> int:
    """Stage 1 retrieves the nearest sharing students in scope; stage 2 reviews each; guardrails apply; the best
    become proposals for staff to approve."""
    from app.agents.matcher import blend, resume_for_prompt, review_fit
    from app.embeddings import get_embedder
    from app.llm import CallContext
    from app.skills import skill_overlap

    if job.embedding is None:
        return 0
    students = [(u, p) for u, p in await sharing_students(session, org.id) if p.embedding is not None and (member is None or in_department(member, p.academics))]
    if not students:
        return 0
    ids = [p.id for _, p in students]
    dist = Profile.embedding.cosine_distance(job.embedding)
    near = (await session.execute(select(Profile.id, dist.label("d")).where(Profile.id.in_(ids)).order_by(dist).limit(RETRIEVE_K))).all()
    by_profile = {p.id: (u, p) for u, p in students}
    embedder = get_embedder()
    existing = set((await session.execute(select(CampusPlacement.user_id).where(CampusPlacement.org_id == org.id, CampusPlacement.job_id == job.id))).scalars())
    cands = []
    for pid, d in near:
        u, p = by_profile[pid]
        if u.id in existing:
            continue
        resume = ResumeData.model_validate(p.resume or {})
        cands.append((u, p, resume, embedder.to_score(1.0 - float(d if d is not None else 1.0))))
    ctx = CallContext(user_id=ctx_user)
    evidence = await campus_evidence(org.id, [u.id for u, _, _, _ in cands])
    reviews = await asyncio.gather(*(review_fit(job, _with_campus(resume_for_prompt(r), evidence.get(u.id, [])), ctx) for u, _, r, _ in cands))
    rows = []
    for (u, p, resume, semantic), review in zip(cands, reviews):
        strengths, gaps, skills = skill_overlap(resume.skills, job.skills or [])
        score = blend(semantic, skills, review.fit_score if review else None)
        factor, notes = _guardrails(job, Preferences.model_validate(p.preferences or {}))
        score *= factor
        if score < PROPOSE_MIN:
            continue
        reasoning = {
            "semantic": round(semantic, 1),
            "skills": round(skills, 1),
            "llm": review.fit_score if review else None,
            "strengths": (review.strengths if review else strengths)[:6],
            "gaps": (review.gaps if review else gaps)[:6],
            "requirements": [r.model_dump() for r in review.requirements][:10] if review else [],
            "explanation": (review.explanation if review else "")[:400],
            "guardrails": notes,
            "campus_evidence": {"verified": sum(e["status"] == "verified" for e in evidence.get(u.id, [])), "self_reported": sum(e["status"] == "self_reported" for e in evidence.get(u.id, []))},
        }
        rows.append((score, u, reasoning))
    rows.sort(key=lambda r: -r[0])
    for score, u, reasoning in rows[:PROPOSE_MAX]:
        cp = CampusPlacement(org_id=org.id, user_id=u.id, job_id=job.id, company=job.company, title=job.title, stage="proposed", source="ai_recommended", match_score=round(score, 1), reasoning=reasoning)
        _hist(cp, "proposed", None, f"AI fit {round(score)}")
        session.add(cp)
    if rows:
        await publish_staff(session, org.id, "campus_update", proposals=len(rows[:PROPOSE_MAX]))
    log.info("placement.proposed", org=str(org.id), job=str(job.id), retrieved=len(cands), proposed=len(rows[:PROPOSE_MAX]))
    return len(rows[:PROPOSE_MAX])


async def propose_from_index(session, org: Organization, min_score: float = 70.0, days: int = 14) -> int:
    """Strong recent matches the students' own agents found become proposals for staff (reasoning included)."""
    students = await sharing_students(session, org.id)
    if not students:
        return 0
    ids = [u.id for u, _ in students]
    since = datetime.now(UTC) - timedelta(days=days)
    existing = {(r.user_id, r.job_id) for r in (await session.execute(select(CampusPlacement.user_id, CampusPlacement.job_id).where(CampusPlacement.org_id == org.id))).all()}
    matches = (
        await session.execute(
            select(JobMatch).where(JobMatch.user_id.in_(ids), JobMatch.score >= min_score, JobMatch.created_at >= since, JobMatch.stage.in_([Stage.found, Stage.shortlisted]))
        )
    ).unique().scalars().all()
    n = 0
    for m in matches:
        if (m.user_id, m.job_id) in existing or m.job is None or m.job.link_status == "dead":
            continue
        cp = CampusPlacement(
            org_id=org.id, user_id=m.user_id, job_id=m.job_id, company=m.job.company, title=m.job.title, stage="proposed", source="ai_recommended", match_score=round(m.score, 1),
            reasoning={"strengths": m.strengths[:6], "gaps": m.gaps[:6], "explanation": (m.explanation or "")[:400], "semantic": m.semantic_score, "skills": m.skill_score, "llm": m.llm_score},
        )
        _hist(cp, "proposed", None, f"Found by the student's crew · fit {round(m.score)}")
        session.add(cp)
        existing.add((m.user_id, m.job_id))
        n += 1
    if n:
        await publish_staff(session, org.id, "campus_update", proposals=n)
    return n


async def precision_at_k(session, org_id, k: int = 5) -> dict:
    """Of the top-k AI proposals per student that staff decided, the share they approved: the ground-truth check on
    the matching. Industry target: P@5 above 0.9."""
    rows = (
        await session.execute(
            select(CampusPlacement.user_id, CampusPlacement.match_score, CampusPlacement.stage).where(
                CampusPlacement.org_id == org_id, CampusPlacement.source == "ai_recommended", CampusPlacement.decided_at.is_not(None)
            )
        )
    ).all()
    per: dict = {}
    for uid, score, stage in rows:
        per.setdefault(uid, []).append((score or 0, stage != "dismissed"))
    hits = total = 0
    for items in per.values():
        top = sorted(items, key=lambda x: -x[0])[:k]
        hits += sum(1 for _, ok in top if ok)
        total += len(top)
    return {"k": k, "precision": round(hits / total, 2) if total else None, "decided": total, "approved": hits}


async def run_proposals_all() -> int:
    """Scheduler: refresh proposals for every college from the students' own strong matches."""
    from app.db import session_scope

    n = 0
    async with session_scope() as s:
        for org in (await s.execute(select(Organization))).scalars().all():
            n += await propose_from_index(s, org)
    return n

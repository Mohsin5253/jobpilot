"""Who may see what in Campus, enforced twice: here (the staff-only API) and in Postgres (row-level security).

Staff portal requests carry a staff token (cookie `jp_staff`, or header `X-Staff-Token`) minted after the staff member
opens the portal: it names the campus, the role and the membership status, and is bound to the account's
token_version, so deactivating someone (which bumps it) ends every staff session at once (401). TPO and Principal
tokens need a one-time code by email first (2FA).

Every staff query runs in `campus_session`: a transaction that switches to the `jobpilot_campus` role (no RLS bypass)
and sets app.campus_role / app.campus_ids / app.user_id / app.dept_ids / app.program_ids / app.batch_ids with SET
LOCAL. The policies (migration 0030) compare row columns with those settings only, so a pending or deactivated member,
a faculty member outside their batch, or a TPO of another campus gets no rows even if a route has a bug."""

import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request
from sqlalchemy import select, text

from app.api.deps import UserDep
from app.config import settings
from app.db import session_scope
from app.models import User

STAFF_ROLES = ("tpo", "principal", "hod", "faculty", "coordinator", "university_admin")
WHOLE_CAMPUS = ("tpo", "principal")
TWO_FACTOR = ("tpo", "principal")
STAFF_TOKEN_HOURS = 12
_role_ok: bool | None = None


@dataclass
class StaffCtx:
    user_id: uuid.UUID
    campus_id: uuid.UUID
    role: str
    membership_id: uuid.UUID
    institution_id: uuid.UUID | None = None
    campus_ids: list[uuid.UUID] = field(default_factory=list)
    dept_ids: list[uuid.UUID] = field(default_factory=list)
    program_ids: list[uuid.UUID] = field(default_factory=list)  # whole programmes (an assignment without a batch)
    batch_ids: list[uuid.UUID] = field(default_factory=list)

    @property
    def whole_campus(self) -> bool:
        return self.role in WHOLE_CAMPUS


def _arr(ids: list[uuid.UUID]) -> str:
    return "{" + ",".join(str(i) for i in ids) + "}"


@asynccontextmanager
async def campus_session(role: str, user_id: uuid.UUID, campus_ids: list[uuid.UUID], dept_ids=(), program_ids=(), batch_ids=()):
    """A transaction under row-level security for this viewer. role '' is never passed here (that's system context)."""
    global _role_ok
    async with session_scope() as s:
        if _role_ok is None:
            _role_ok = bool((await s.execute(text("SELECT pg_has_role(current_user, 'jobpilot_campus', 'MEMBER') FROM pg_roles WHERE rolname = 'jobpilot_campus'"))).scalar())
        # One round trip: the role switch (set_config('role') is SET LOCAL ROLE) and every app.* setting, transaction-local.
        await s.execute(
            text(
                "SELECT set_config('app.campus_role', :r, true), set_config('app.user_id', :u, true), set_config('app.campus_ids', :c, true), "
                "set_config('app.dept_ids', :d, true), set_config('app.program_ids', :p, true), set_config('app.batch_ids', :b, true)"
                + (", set_config('role', 'jobpilot_campus', true)" if _role_ok else "")
            ),
            {"r": role or "none", "u": str(user_id), "c": _arr(list(campus_ids)), "d": _arr(list(dept_ids)), "p": _arr(list(program_ids)), "b": _arr(list(batch_ids))},
        )
        yield s


def staff_session(ctx: StaffCtx):
    return campus_session(ctx.role, ctx.user_id, ctx.campus_ids or [ctx.campus_id], ctx.dept_ids, ctx.program_ids, ctx.batch_ids)


def student_session(user_id: uuid.UUID):
    return campus_session("student", user_id, [])


# ---------- staff tokens ----------


def mint_staff_token(user: User, membership_id: uuid.UUID, campus_id: uuid.UUID, role: str, status: str) -> str:
    now = datetime.now(UTC)
    payload = {"sub": str(user.id), "kind": "campus_staff", "mid": str(membership_id), "campus_id": str(campus_id), "campus_role": role,
               "membership_status": status, "ver": user.token_version, "iat": now, "exp": now + timedelta(hours=STAFF_TOKEN_HOURS)}
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def read_staff_token(token: str) -> dict | None:
    try:
        p = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
    return p if p.get("kind") == "campus_staff" else None


async def load_scope(s, user_id: uuid.UUID, campus_id: uuid.UUID, role: str, membership_id: uuid.UUID) -> StaffCtx:
    from app.campus.models import Campus, StaffAssignment

    ctx = StaffCtx(user_id=user_id, campus_id=campus_id, role=role, membership_id=membership_id)
    if role == "university_admin":
        inst = (await s.execute(select(Campus.institution_id).where(Campus.id == campus_id))).scalar_one()
        ctx.institution_id = inst
        ctx.campus_ids = list((await s.execute(select(Campus.id).where(Campus.institution_id == inst))).scalars())
        return ctx
    rows = (await s.execute(select(StaffAssignment).where(StaffAssignment.campus_id == campus_id, StaffAssignment.user_id == user_id, StaffAssignment.status == "approved"))).scalars().all()
    for a in rows:
        if a.batch_id:
            ctx.batch_ids.append(a.batch_id)
        elif a.program_id:
            ctx.program_ids.append(a.program_id)
        elif a.department_id:
            ctx.dept_ids.append(a.department_id)
    return ctx


async def staff_ctx(request: Request, user: UserDep) -> StaffCtx:
    """The gate for every /api/campus/staff/** route: an active, approved staff membership with a valid staff token for
    the current account version; otherwise 401 (token gone or revoked) or 403 (not staff, or not approved yet)."""
    from app.campus.models import CampusMembership

    token = request.headers.get("x-staff-token") or request.cookies.get("jp_staff")
    claims = read_staff_token(token) if token else None
    if not claims or claims.get("sub") != str(user.id):
        async with session_scope() as s:  # not staff at all (a student, whatever URL or code they have): forbidden
            staff = (await s.execute(select(CampusMembership.id).where(CampusMembership.user_id == user.id, CampusMembership.kind == "staff", CampusMembership.status == "active"))).first()
        if staff is None:
            raise HTTPException(403, "The Campus portal is for approved college staff only")
        raise HTTPException(403, "staff_session_required: open the Campus portal again")
    if int(claims.get("ver", -1)) != user.token_version:  # unreachable for a live account: current_user already 401s
        raise HTTPException(401, "Your staff session was ended. Sign in again.")
    if claims.get("campus_role") not in STAFF_ROLES or claims.get("membership_status") != "active":
        raise HTTPException(403, "The Campus portal is for approved college staff only")
    campus_id = uuid.UUID(claims["campus_id"])
    # The membership and approved assignments, cached 30 s per account version: deactivation bumps the version (so it
    # still ends access on the very next request), and a changed assignment applies within 30 seconds.
    key = (user.id, campus_id, user.token_version)
    hit_ = _scope_cache.get(key)
    if hit_ and hit_[0] > _now():
        return hit_[1]
    async with session_scope() as s:  # the membership must still be active right now (not just when the token was issued)
        m = (await s.execute(select(CampusMembership).where(CampusMembership.campus_id == campus_id, CampusMembership.user_id == user.id, CampusMembership.kind == "staff"))).scalar_one_or_none()
        if m is None or m.status != "active" or m.role not in STAFF_ROLES:
            raise HTTPException(403, "The Campus portal is for approved college staff only")
        ctx = await load_scope(s, user.id, campus_id, m.role, m.id)
    if len(_scope_cache) > 20_000:
        _scope_cache.clear()
    _scope_cache[key] = (_now() + SCOPE_TTL_S, ctx)
    return ctx


SCOPE_TTL_S = 30.0
_scope_cache: dict[tuple, tuple[float, StaffCtx]] = {}


def _now() -> float:
    import time

    return time.monotonic()


def forget_scope(user_id: uuid.UUID | None = None) -> None:
    """Drop cached scopes (all, or one person's) after an approval or assignment change on this process."""
    for k in [k for k in _scope_cache if user_id is None or k[0] == user_id]:
        _scope_cache.pop(k, None)


StaffDep = Annotated[StaffCtx, Depends(staff_ctx)]


def require(ctx: StaffCtx, *roles: str) -> None:
    if ctx.role not in roles:
        raise HTTPException(403, "Your campus role can't do that")


async def audit(ctx: StaffCtx, action: str, subject_user_id: uuid.UUID | None = None, **detail) -> None:
    """Who, what, when, campus: every staff login, view of an individual student, approval, verification and export."""
    from app.campus.ids import uuid7
    from app.campus.models import StaffAudit

    async with session_scope() as s:
        s.add(StaffAudit(id=uuid7(), campus_id=ctx.campus_id, actor_user_id=ctx.user_id, action=action, subject_user_id=subject_user_id, detail=detail))

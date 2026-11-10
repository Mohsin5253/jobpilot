"""Privacy & consent: each optional purpose can be granted or withdrawn at any time."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import RealUserDep, SessionDep, UserDep
from app.config import settings
from app.models import Consent
from app.services.consent import NOTICE, PURPOSES, active, grant, withdraw

router = APIRouter(prefix="/consents", tags=["consent"])


class ConsentIn(BaseModel):
    granted: bool


@router.get("")
async def list_consents(user: UserDep, session: SessionDep) -> dict:
    current = await active(session, user.id)
    return {
        "version": settings.consent_version,
        "purposes": [
            {
                "purpose": p,
                "description": text,
                "granted": p in current,
                "granted_at": current[p].granted_at.isoformat() if p in current else None,
                "notice_version": current[p].notice_version if p in current else None,
                "method": current[p].method if p in current else None,
                "required": p == "core",
                "notice": NOTICE[p],
            }
            for p, text in PURPOSES.items()
        ],
    }


@router.get("/notice")
async def notice() -> dict:
    """The itemized consent notice, public (shown before sign-up)."""
    return {"version": settings.consent_version, "purposes": [{"purpose": p, "description": t, **NOTICE[p]} for p, t in PURPOSES.items()]}


@router.get("/history")
async def history(user: UserDep, session: SessionDep) -> list[dict]:
    """Every consent record, including withdrawn ones: what, when, how, and which notice version."""
    rows = (await session.execute(select(Consent).where(Consent.user_id == user.id).order_by(Consent.granted_at.desc()))).scalars().all()
    return [
        {"purpose": c.purpose, "notice_version": c.notice_version, "method": c.method, "granted_at": c.granted_at.isoformat(),
         "withdrawn_at": c.withdrawn_at.isoformat() if c.withdrawn_at else None}
        for c in rows
    ]


@router.put("/{purpose}")
async def set_consent(purpose: str, body: ConsentIn, user: RealUserDep, session: SessionDep) -> dict:
    if purpose not in PURPOSES:
        raise HTTPException(404, "Unknown purpose")
    if purpose == "core" and not body.granted:
        raise HTTPException(409, "Core processing is what JobPilot does. To stop it, delete your account in Settings → Your data.")
    if body.granted:
        await grant(session, user.id, purpose)
    else:
        await withdraw(session, user.id, purpose)
    await session.commit()
    return await list_consents(user, session)

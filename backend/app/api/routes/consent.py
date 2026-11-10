"""Privacy & consent: each optional purpose can be granted or withdrawn at any time."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.api.deps import RealUserDep, SessionDep, UserDep
from app.config import settings
from app.services.consent import PURPOSES, active, grant, withdraw

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
                "required": p == "core",
            }
            for p, text in PURPOSES.items()
        ],
    }


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

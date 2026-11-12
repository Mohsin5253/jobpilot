"""WhatsApp daily digest: your number and hour, a test message, and the Cloud API webhook."""

from datetime import UTC, datetime

import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import RealUserDep, SessionDep, UserDep
from app.config import settings
from app.models import Profile
from app.services.consent import grant, has, withdraw
from app.services.ratelimit import hit
from app.services.whatsapp import digest_for, handle_inbound, normalize_number, send_template, valid_signature
from app.safety import egress

router = APIRouter(prefix="/whatsapp", tags=["whatsapp"])


class WhatsAppIn(BaseModel):
    number: str = Field(min_length=10, max_length=20)
    hour: int = Field(default=8, ge=0, le=23)
    consent: bool


async def _profile(session, user_id) -> Profile:
    return (await session.execute(select(Profile).where(Profile.user_id == user_id))).scalar_one()


async def _out(session, p: Profile) -> dict:
    return {
        "available": settings.whatsapp_enabled,
        "number": p.whatsapp_number,
        "hour": p.whatsapp_hour_local,
        "enabled": bool(p.whatsapp_number) and await has(session, p.user_id, "whatsapp"),
        "last_sent_at": p.whatsapp_last_sent_at.isoformat() if p.whatsapp_last_sent_at else None,
    }


@router.get("")
async def get_whatsapp(user: UserDep, session: SessionDep) -> dict:
    return await _out(session, await _profile(session, user.id))


@router.put("")
async def set_whatsapp(body: WhatsAppIn, user: RealUserDep, session: SessionDep) -> dict:
    if not body.consent:
        raise HTTPException(422, "Tick the box to agree to receive the daily WhatsApp digest")
    number = normalize_number(body.number)
    if number is None:
        raise HTTPException(422, "Enter a mobile number with country code, e.g. +91 98765 43210")
    p = await _profile(session, user.id)
    p.whatsapp_number, p.whatsapp_hour_local = number, body.hour
    await grant(session, user.id, "whatsapp")
    await session.commit()
    return await _out(session, p)


@router.delete("")
async def stop_whatsapp(user: UserDep, session: SessionDep) -> dict:
    p = await _profile(session, user.id)
    p.whatsapp_number = None
    await withdraw(session, user.id, "whatsapp")
    await session.commit()
    return await _out(session, p)


@router.post("/test")
async def send_test(user: RealUserDep, session: SessionDep) -> dict:
    """Send today's digest now, to check the number works."""
    if not settings.whatsapp_enabled:
        raise HTTPException(409, "WhatsApp isn't set up on this server yet")
    await hit("whatsapp", str(user.id))
    p = await _profile(session, user.id)
    if not p.whatsapp_number or not await has(session, user.id, "whatsapp"):
        raise HTTPException(409, "Add your number and agree to the digest first")
    now = datetime.now(UTC)
    digest = await digest_for(session, p, now) or (((p.resume or {}).get("name") or "there").split(" ")[0], "No new strong fits in the last 24 hours yet. Your agents are still watching.")
    try:
        async with egress.client("whatsapp") as client:
            await send_template(client, p.whatsapp_number, list(digest))
    except httpx.HTTPError as exc:
        raise HTTPException(502, "WhatsApp didn't accept the message. Check the number, and that the template is approved.") from exc
    p.whatsapp_last_sent_at = now
    await session.commit()
    return {"detail": "Sent"}


@router.get("/webhook", include_in_schema=False)
async def verify_webhook(
    mode: str = Query(alias="hub.mode", default=""), token: str = Query(alias="hub.verify_token", default=""), challenge: str = Query(alias="hub.challenge", default="")
) -> PlainTextResponse:
    if mode == "subscribe" and settings.whatsapp_verify_token and token == settings.whatsapp_verify_token:
        return PlainTextResponse(challenge)
    raise HTTPException(403, "Verification failed")


@router.post("/webhook", include_in_schema=False)
async def inbound(request: Request) -> dict:
    body = await request.body()
    if not valid_signature(body, request.headers.get("x-hub-signature-256")):
        raise HTTPException(401, "Bad signature")
    stopped = await handle_inbound(await request.json())
    return {"ok": True, "opted_out": stopped}

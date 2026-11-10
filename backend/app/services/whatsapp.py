"""WhatsApp daily digest through the official WhatsApp Cloud API.

Once a day, at the hour the student picked (IST), their 3-5 best new fits go out as one approved template
message, with a link to the approvals queue. Only with the `whatsapp` consent, only to the number they gave,
at most once a day. Replying STOP withdraws the consent (via the webhook). Off until the WHATSAPP_* keys
are set; everyone keeps in-app and email alerts either way.
"""

import hashlib
import hmac
import re
from datetime import UTC, datetime, timedelta, timezone

import httpx
from sqlalchemy import select, text

from app.config import settings
from app.db import session_scope
from app.logging import log
from app.models import Job, JobMatch, Profile
from app.schemas import Preferences
from app.services.consent import has, withdraw

GRAPH = "https://graph.facebook.com/v21.0"
IST = timezone(timedelta(hours=5, minutes=30))
STOP_WORDS = {"stop", "unsubscribe", "cancel", "band karo"}


def normalize_number(raw: str) -> str | None:
    """E.164 digits for the Cloud API ("919876543210"). Indian 10-digit mobiles get the 91 prefix."""
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 10 and digits[0] in "6789":
        digits = "91" + digits
    elif len(digits) == 11 and digits.startswith("0"):
        digits = "91" + digits[1:]
    return digits if 11 <= len(digits) <= 15 else None


def _clean(param: str) -> str:
    # Template parameters can't hold newlines, tabs or more than 4 spaces in a row.
    return re.sub(r"\s+", " ", param).strip()[:900]


async def send_template(client: httpx.AsyncClient, to: str, params: list[str]) -> dict:
    r = await client.post(
        f"{GRAPH}/{settings.whatsapp_phone_number_id}/messages",
        headers={"Authorization": f"Bearer {settings.whatsapp_token}"},
        json={
            "messaging_product": "whatsapp",
            "to": to,
            "type": "template",
            "template": {
                "name": settings.whatsapp_template,
                "language": {"code": settings.whatsapp_template_lang},
                "components": [{"type": "body", "parameters": [{"type": "text", "text": _clean(p)} for p in params]}],
            },
        },
        timeout=20,
    )
    r.raise_for_status()
    return r.json()


async def digest_for(s, profile: Profile, now: datetime) -> tuple[str, str] | None:
    """(first name, one-line summary of the best new fits), or None when there's nothing worth sending."""
    prefs = Preferences.model_validate(profile.preferences or {})
    rows = (
        await s.execute(
            select(JobMatch, Job)
            .join(Job, Job.id == JobMatch.job_id)
            .where(JobMatch.user_id == profile.user_id, JobMatch.created_at >= now - timedelta(hours=24), JobMatch.score >= prefs.min_score, Job.ghost_risk != "high")
            .order_by(JobMatch.score.desc())
            .limit(5)
        )
    ).unique().all()
    if not rows:
        return None
    first = ((profile.resume or {}).get("name") or "there").split(" ")[0]
    items = " · ".join(f"{i}) {j.title} at {j.company} ({round(m.score)} fit)" for i, (m, j) in enumerate(rows, 1))
    return first, f"{len(rows)} new role(s) fit you today: {items}. Drafts are ready to review: {settings.app_url.rstrip('/')}/approvals"


async def digest_sweep(now: datetime | None = None) -> int:
    """Hourly: send today's digest to everyone whose chosen hour (IST) is now. Advisory-locked across workers."""
    if not settings.whatsapp_enabled:
        return 0
    now = now or datetime.now(UTC)
    hour = now.astimezone(IST).hour
    sent = 0
    async with session_scope() as s:
        if not (await s.execute(text("SELECT pg_try_advisory_xact_lock(724006)"))).scalar():
            return 0
        profiles = (
            await s.execute(
                select(Profile).where(
                    Profile.whatsapp_number.is_not(None),
                    Profile.whatsapp_hour_local == hour,
                    (Profile.whatsapp_last_sent_at.is_(None)) | (Profile.whatsapp_last_sent_at < now - timedelta(hours=20)),
                )
            )
        ).scalars().all()
        async with httpx.AsyncClient() as client:
            for p in profiles:
                if not await has(s, p.user_id, "whatsapp"):
                    continue
                digest = await digest_for(s, p, now)
                if digest is None:
                    continue
                try:
                    await send_template(client, p.whatsapp_number, list(digest))
                except httpx.HTTPError as exc:
                    log.warning("whatsapp.send_failed", error=str(exc)[:200])
                    continue
                p.whatsapp_last_sent_at = now
                sent += 1
    if sent:
        log.info("whatsapp.digests_sent", count=sent)
    return sent


def valid_signature(body: bytes, header: str | None) -> bool:
    if not settings.whatsapp_app_secret or not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(settings.whatsapp_app_secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.removeprefix("sha256="))


async def handle_inbound(payload: dict) -> int:
    """STOP (or similar) from a number withdraws that user's WhatsApp consent. Returns how many opted out."""
    stopped = 0
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            for msg in (change.get("value") or {}).get("messages", []):
                body = ((msg.get("text") or {}).get("body") or (msg.get("button") or {}).get("text") or "").strip().lower()
                if body not in STOP_WORDS:
                    continue
                number = normalize_number(msg.get("from", ""))
                async with session_scope() as s:
                    for p in (await s.execute(select(Profile).where(Profile.whatsapp_number == number))).scalars():
                        await withdraw(s, p.user_id, "whatsapp")
                        stopped += 1
    return stopped

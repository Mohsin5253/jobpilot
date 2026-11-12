"""WhatsApp daily digest and approvals through the official WhatsApp Cloud API.

Once a day, at the hour the student picked (IST), their 3-5 best new fits go out as one approved template
message, with a link to the approvals queue. Only with the `whatsapp` consent, only to the number they gave,
at most once a day. Replying STOP withdraws the consent (via the webhook). Off until the WHATSAPP_* keys
are set; everyone keeps in-app and email alerts either way.

Approvals (F6): with WHATSAPP_APPROVAL_TEMPLATE approved, the digest is followed by the 3-5 best drafts that are
ready to approve, each with quick-reply buttons Approve / Edit in app / Skip. A button's payload is signed and bound
to the draft, the student's number and their current session version (signing out everywhere voids it), and expires
after 24 hours. Approving goes through exactly the same checks as the web (scam block, daily quota, audit event with
channel 'whatsapp'), then Dispatch sends it. Webhook deliveries are idempotent by message id.
"""

import hashlib
import hmac
import re
from datetime import UTC, datetime, timedelta, timezone

import httpx

from app.safety import egress
from sqlalchemy import select, text

from app.config import settings
from app.db import session_scope
from app.logging import log
from app.models import Job, JobMatch, OutreachDraft, Profile, User
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


# Localized text for digests and replies (UI strings live in the web app's dictionaries).
T: dict[str, dict[str, str]] = {
    "digest": {
        "en": "{n} new role(s) fit you today: {items}. Drafts are ready to review: {url}",
        "hi": "आज {n} नई भूमिकाएँ आपके लिए सही हैं: {items}. ड्राफ़्ट देखने के लिए तैयार हैं: {url}",
        "mr": "आज {n} नवीन भूमिका तुमच्यासाठी योग्य आहेत: {items}. ड्राफ्ट तपासण्यासाठी तयार आहेत: {url}",
    },
    "item": {"en": "{title} at {company} ({score} fit)", "hi": "{company} में {title} ({score} फ़िट)", "mr": "{company} येथे {title} ({score} फिट)"},
    "approved": {
        "en": "Approved: your application to {company} is going out from your own mailbox.",
        "hi": "मंज़ूर: {company} को आपका आवेदन आपके अपने ईमेल से भेजा जा रहा है।",
        "mr": "मंजूर: {company} साठी तुमचा अर्ज तुमच्या स्वतःच्या ईमेलवरून पाठवला जात आहे.",
    },
    "approved_manual": {
        "en": "Approved. Connect your email in Settings to send it, or open it here: {url}",
        "hi": "मंज़ूर। भेजने के लिए सेटिंग्स में अपना ईमेल जोड़ें, या यहाँ खोलें: {url}",
        "mr": "मंजूर. पाठवण्यासाठी सेटिंग्जमध्ये तुमचा ईमेल जोडा, किंवा येथे उघडा: {url}",
    },
    "skipped": {"en": "Skipped. It stays in your queue.", "hi": "छोड़ दिया। यह आपकी सूची में रहेगा।", "mr": "वगळले. ते तुमच्या यादीत राहील."},
    "edit": {"en": "Edit it here: {url}", "hi": "यहाँ बदलें: {url}", "mr": "येथे बदला: {url}"},
    "refused": {"en": "Couldn't approve: {reason}", "hi": "मंज़ूर नहीं हो सका: {reason}", "mr": "मंजूर करता आले नाही: {reason}"},
    "expired": {
        "en": "That button has expired or isn't valid any more. Open your queue: {url}",
        "hi": "यह बटन अब मान्य नहीं है। अपनी सूची खोलें: {url}",
        "mr": "हे बटण आता वैध नाही. तुमची यादी उघडा: {url}",
    },
}


def t(key: str, lang: str, **kw) -> str:
    table = T[key]
    return table.get(lang, table["en"]).format(**kw)


def _lang(lang: str) -> str:
    return lang if lang in settings.whatsapp_template_langs else "en"


async def _post(client: httpx.AsyncClient, body: dict, actor: str = "digest") -> dict:
    # The choke point for every WhatsApp message: only the digest job and replies to a student's own tap, only to a
    # number whose owner has the 'whatsapp' consent active, and never while the kill switch is on.
    from app.safety import policy

    await policy.authorize(actor, "whatsapp.send", ctx=await policy.whatsapp_context(body.get("to", "")))
    r = await client.post(
        f"{GRAPH}/{settings.whatsapp_phone_number_id}/messages",
        headers={"Authorization": f"Bearer {settings.whatsapp_token}"},
        json={"messaging_product": "whatsapp", **body},
        timeout=20,
    )
    r.raise_for_status()
    return r.json()


async def send_template(client: httpx.AsyncClient, to: str, params: list[str], lang: str = "en") -> dict:
    return await _post(
        client,
        {
            "to": to,
            "type": "template",
            "template": {
                "name": settings.whatsapp_template,
                "language": {"code": _lang(lang) if lang != "en" else settings.whatsapp_template_lang},
                "components": [{"type": "body", "parameters": [{"type": "text", "text": _clean(p)} for p in params]}],
            },
        },
    )


async def send_text(client: httpx.AsyncClient, to: str, body: str) -> dict:
    """A free-form reply: allowed inside the 24-hour window the student's button tap opened."""
    return await _post(client, {"to": to, "type": "text", "text": {"body": body[:4000]}}, actor="whatsapp_reply")


def sign_action(action: str, draft_id: str, user: User, now: datetime | None = None) -> str:
    exp = int(((now or datetime.now(UTC)) + timedelta(hours=24)).timestamp())
    msg = f"{action}:{draft_id}:{exp}:{user.token_version}"
    sig = hmac.new(settings.jwt_secret.encode(), f"wa:{user.id}:{msg}".encode(), hashlib.sha256).hexdigest()[:20]
    return f"jp:{msg}:{sig}"


def check_action(payload: str, user: User, now: datetime | None = None) -> tuple[str, str] | None:
    """(action, draft_id) when the payload is genuine, unexpired and from this user's current session version."""
    try:
        _, action, draft_id, exp, tv, sig = payload.split(":")
    except ValueError:
        return None
    msg = f"{action}:{draft_id}:{exp}:{tv}"
    good = hmac.new(settings.jwt_secret.encode(), f"wa:{user.id}:{msg}".encode(), hashlib.sha256).hexdigest()[:20]
    if not hmac.compare_digest(sig, good) or int(tv) != user.token_version or int(exp) < (now or datetime.now(UTC)).timestamp():
        return None
    return action, draft_id


async def send_approval_items(client: httpx.AsyncClient, s, profile: Profile, user: User) -> int:
    """The best 3-5 drafts ready to approve, one template message each with Approve / Edit in app / Skip."""
    if not settings.whatsapp_approval_template:
        return 0
    from app.services import quota

    rows = (
        await s.execute(
            select(OutreachDraft, JobMatch, Job)
            .join(JobMatch, JobMatch.id == OutreachDraft.match_id)
            .join(Job, Job.id == JobMatch.job_id)
            .where(OutreachDraft.user_id == user.id, OutreachDraft.status == "pending", Job.legit_status.is_distinct_from("suspicious"))
            .order_by(JobMatch.score.desc())
            .limit(10)
        )
    ).all()
    scored = sorted([((await quota.draft_worthiness(s, d, m, j))[0], d, j) for d, m, j in rows], key=lambda x: -x[0])[:5]
    sent = 0
    for worth, d, j in scored:
        if worth < 50:
            continue
        buttons = [
            {"type": "button", "sub_type": "quick_reply", "index": str(i), "parameters": [{"type": "payload", "payload": sign_action(a, str(d.id), user)}]}
            for i, a in enumerate(("approve", "edit", "skip"))
        ]
        await _post(
            client,
            {
                "to": profile.whatsapp_number,
                "type": "template",
                "template": {
                    "name": settings.whatsapp_approval_template,
                    "language": {"code": _lang(user.language)},
                    "components": [{"type": "body", "parameters": [{"type": "text", "text": _clean(x)} for x in (j.title, j.company, f"{worth}/100")]}, *buttons],
                },
            },
        )
        sent += 1
    return sent


async def digest_for(s, profile: Profile, now: datetime, lang: str = "en") -> tuple[str, str] | None:
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
    items = " · ".join(f"{i}) " + t("item", lang, title=j.title, company=j.company, score=round(m.score)) for i, (m, j) in enumerate(rows, 1))
    return first, t("digest", lang, n=len(rows), items=items, url=f"{settings.app_url.rstrip('/')}/approvals")


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
        async with egress.client("whatsapp") as client:
            for p in profiles:
                if not await has(s, p.user_id, "whatsapp"):
                    continue
                user = await s.get(User, p.user_id)
                digest = await digest_for(s, p, now, user.language)
                if digest is None:
                    continue
                try:
                    await send_template(client, p.whatsapp_number, list(digest), user.language)
                    await send_approval_items(client, s, p, user)
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
    """STOP withdraws the WhatsApp consent; Approve / Edit / Skip buttons act on a draft. Each message id is handled
    once, however often Meta retries the webhook. Returns how many messages were acted on."""
    acted = 0
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            for msg in (change.get("value") or {}).get("messages", []):
                mid = msg.get("id")
                async with session_scope() as s:
                    if mid:
                        fresh = (await s.execute(text("INSERT INTO whatsapp_events (id) VALUES (:id) ON CONFLICT DO NOTHING RETURNING id"), {"id": mid})).first()
                        if fresh is None:
                            continue  # a retry of a message we already handled
                    number = normalize_number(msg.get("from", ""))
                    button = (msg.get("button") or {}).get("payload") or ((msg.get("interactive") or {}).get("button_reply") or {}).get("id") or ""
                    body = ((msg.get("text") or {}).get("body") or (msg.get("button") or {}).get("text") or "").strip().lower()
                    profiles = (await s.execute(select(Profile).where(Profile.whatsapp_number == number))).scalars().all()
                    if body in STOP_WORDS:
                        for p in profiles:
                            await withdraw(s, p.user_id, "whatsapp")
                            acted += 1
                    elif button.startswith("jp:") and len(profiles) == 1:
                        acted += await _button(s, profiles[0], number, button)
    return acted


async def _button(s, profile: Profile, number: str, payload: str) -> int:
    from fastapi import HTTPException

    from app.api.routes.drafts import approve
    from app.models import DraftStatus

    user = await s.get(User, profile.user_id)
    url = f"{settings.app_url.rstrip('/')}/approvals"
    lang = user.language
    checked = check_action(payload, user)
    reply = t("expired", lang, url=url)
    send_after = None
    if checked and await has(s, user.id, "whatsapp"):
        action, draft_id = checked
        row = (
            await s.execute(
                select(OutreachDraft, JobMatch, Job)
                .join(JobMatch, JobMatch.id == OutreachDraft.match_id)
                .join(Job, Job.id == JobMatch.job_id)
                .where(OutreachDraft.id == draft_id, OutreachDraft.user_id == user.id)
                .with_for_update(of=OutreachDraft)
            )
        ).first()
        if row is None or row[0].status != DraftStatus.pending:
            reply = t("expired", lang, url=url)
        elif action == "approve":
            d, m, j = row
            try:
                await approve(s, user, d, m, j, "whatsapp")
                from app.services.mailer import user_sender

                connected = await user_sender(user.id) is not None
                # A draft from a run is sent by Dispatch when the run resumes; a standalone one is sent now.
                send_after = d.id if connected and d.run_id is None else None
                reply = t("approved", lang, company=j.company) if connected else t("approved_manual", lang, url=url)
            except HTTPException as exc:
                reply = t("refused", lang, reason=exc.detail)
        elif action == "skip":
            from app.services import quota

            await quota.record(s, row[0].id, user.id, "skip", "whatsapp")
            reply = t("skipped", lang)
        elif action == "edit":
            reply = t("edit", lang, url=f"{url}?draft={draft_id}")
    await s.commit()
    if send_after:
        from app.services.applications import send_application

        try:
            await send_application(send_after, wait=True, channel="whatsapp")
        except Exception as exc:  # stays approved; the student can send it from the app
            log.warning("whatsapp.dispatch_failed", error=str(exc)[:200])
    if settings.whatsapp_enabled:
        try:
            async with egress.client("whatsapp") as client:
                await send_text(client, number, reply)
        except httpx.HTTPError as exc:
            log.warning("whatsapp.reply_failed", error=str(exc)[:200])
    return 1

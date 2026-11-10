"""Your account: your own outgoing mailbox, plan & usage, data export and deletion."""

import smtplib
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy import delete, select

from app.api.deps import RealUserDep, SessionDep, UserDep
from app.config import settings
from app.logging import log
from app.models import AgentRun, Consent, JobMatch, MailAccount, Notification, OutreachDraft, Profile, RightsRequest, SkillQuestion, User
from app.schemas import MailAccountIn, MailAccountOut
from app.security import COOKIE_NAME, decrypt_secret, encrypt_secret, verify_password
from app.services import gmail
from app.services.consent import grant, withdraw
from app.services.mailer import Sender, verify_login
from app.services.ratelimit import hit
from app.services.usage import usage_today

router = APIRouter(tags=["account"])


def _mail_out(acct: MailAccount | None) -> MailAccountOut:
    google = settings.google_mail_enabled
    if acct is None:
        return MailAccountOut(connected=False, google_available=google)
    return MailAccountOut(
        connected=True, provider=acct.provider, google_available=google, host=acct.host, port=acct.port,
        from_email=acct.from_email, from_name=acct.from_name, verified_at=acct.verified_at,
    )


@router.get("/mail-account", response_model=MailAccountOut)
async def get_mail_account(user: UserDep, session: SessionDep) -> MailAccountOut:
    return _mail_out(await session.get(MailAccount, user.id))


@router.put("/mail-account", response_model=MailAccountOut)
async def connect_mail_account(body: MailAccountIn, user: RealUserDep, session: SessionDep) -> MailAccountOut:
    """Checks the login with the mail server (nothing is sent), then stores it with the password encrypted."""
    await hit("mail_verify", str(user.id))
    password = "".join(body.password.split())  # Gmail shows app passwords in groups of four
    sender = Sender(body.host.strip(), body.port, str(body.username), password, str(body.username), body.from_name.strip() or user.name)
    try:
        await verify_login(sender)
    except smtplib.SMTPAuthenticationError as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "The mail server rejected that email and password. For Gmail, turn on 2-Step Verification and use a 16-character app password.",
        ) from exc
    except (smtplib.SMTPException, OSError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Couldn't reach {body.host}:{body.port} ({type(exc).__name__}). Check the server and port.") from exc
    acct = await session.get(MailAccount, user.id) or MailAccount(user_id=user.id)
    if acct.provider == "gmail_oauth" and acct.refresh_token_enc:
        await gmail.revoke(decrypt_secret(acct.refresh_token_enc) or "")
    acct.provider, acct.refresh_token_enc = "smtp", None
    acct.host, acct.port, acct.username, acct.from_email = sender.host, sender.port, str(body.username), str(body.username)
    acct.from_name = sender.from_name
    acct.password_enc = encrypt_secret(password)
    acct.verified_at = datetime.now(UTC)
    session.add(acct)
    await grant(session, user.id, "sending", method="app_password")
    await session.commit()
    return _mail_out(acct)


@router.delete("/mail-account", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect_mail_account(user: UserDep, session: SessionDep) -> None:
    """Disconnecting deletes the stored credential, tells Google to drop its grant, and ends the 'sending' consent."""
    acct = await session.get(MailAccount, user.id)
    if acct and acct.provider == "gmail_oauth" and acct.refresh_token_enc:
        await gmail.revoke(decrypt_secret(acct.refresh_token_enc) or "")
    await session.execute(delete(MailAccount).where(MailAccount.user_id == user.id))
    await withdraw(session, user.id, "sending")
    await session.commit()


@router.get("/mail/google/start")
async def google_start(user: RealUserDep) -> dict:
    """The Google consent screen URL (gmail.send scope only). The browser navigates there."""
    if not settings.google_mail_enabled:
        raise HTTPException(404, "Google sign-in for sending isn't set up on this server")
    await hit("mail_verify", str(user.id))
    return {"url": gmail.auth_url(gmail.make_state(user.id), login_hint=user.email)}


@router.get("/mail/google/callback")
async def google_callback(user: RealUserDep, session: SessionDep, state: str = "", code: str = "", error: str = "") -> RedirectResponse:
    back = f"{settings.app_url.rstrip('/')}/settings"
    if error or not code:
        return RedirectResponse(f"{back}?mail=cancelled#mail", status_code=303)
    if not gmail.check_state(state, user.id):
        return RedirectResponse(f"{back}?mail=expired#mail", status_code=303)
    try:
        refresh, email = await gmail.exchange_code(code)
    except gmail.GmailError as exc:
        log.warning("mail.google_connect_failed", error=str(exc)[:200])
        return RedirectResponse(f"{back}?mail=failed#mail", status_code=303)
    acct = await session.get(MailAccount, user.id) or MailAccount(user_id=user.id)
    acct.provider, acct.host, acct.port = "gmail_oauth", "gmail.googleapis.com", 443
    acct.username = acct.from_email = email
    acct.from_name = acct.from_name or user.name
    acct.password_enc = None  # the app password (if any) is gone for good
    acct.refresh_token_enc = encrypt_secret(refresh)
    acct.verified_at = datetime.now(UTC)
    session.add(acct)
    await grant(session, user.id, "sending", method="google_oauth")
    await session.commit()
    return RedirectResponse(f"{back}?mail=connected#mail", status_code=303)


class QuotaIn(BaseModel):
    cap: int


@router.get("/quota")
async def get_quota(user: UserDep, session: SessionDep) -> dict:
    """Today's quality quota: approved sends used, the cap, and the plan's maximum."""
    from app.services import quota

    return await quota.state(session, user)


@router.put("/quota")
async def put_quota(body: QuotaIn, user: RealUserDep, session: SessionDep) -> dict:
    from app.services import quota

    await quota.set_cap(session, user, body.cap)
    await session.commit()
    return await quota.state(session, user)


class LanguageIn(BaseModel):
    language: str


@router.put("/account/language")
async def set_language(body: LanguageIn, user: UserDep, session: SessionDep) -> dict:
    """English, Hindi or Marathi: the app's labels, WhatsApp digests and replies."""
    if body.language not in ("en", "hi", "mr"):
        raise HTTPException(422, "Choose en, hi or mr")
    user.language = body.language
    await session.commit()
    return {"language": user.language}


class AgeIn(BaseModel):
    adult: bool


@router.post("/account/age")
async def confirm_age(body: AgeIn, user: RealUserDep, session: SessionDep) -> dict:
    """Age gate for accounts created before it existed. Under 18: nothing is processed (no runs) until a parent's
    verifiable consent can be collected; the account can still be exported or deleted."""
    if not body.adult:
        user.adult_confirmed_at = None
        await session.commit()
        raise HTTPException(status.HTTP_403_FORBIDDEN, "JobPilot can't process data for students under 18 yet. You can export or delete your account in Settings.")
    user.adult_confirmed_at = user.adult_confirmed_at or datetime.now(UTC)
    await session.commit()
    return {"adult_confirmed_at": user.adult_confirmed_at.isoformat()}


@router.get("/usage")
async def usage(user: UserDep, session: SessionDep) -> dict:
    return {**await usage_today(session, user), "pro_requested": bool(user.pro_interest_at)}


@router.post("/account/pro-interest", status_code=status.HTTP_202_ACCEPTED)
async def pro_interest(user: RealUserDep, session: SessionDep) -> dict:
    """No payments yet: records the request; an admin turns Pro on from /admin."""
    user.pro_interest_at = user.pro_interest_at or datetime.now(UTC)
    await session.commit()
    return {"detail": "Thanks! We'll switch your account to Pro and let you know."}


@router.get("/account/export")
async def export(user: UserDep, session: SessionDep) -> JSONResponse:
    """Everything JobPilot holds about you, as one JSON file (India's DPDP Act / GDPR access right)."""
    profile = (await session.execute(select(Profile).where(Profile.user_id == user.id))).scalar_one_or_none()
    matches = (await session.execute(select(JobMatch).where(JobMatch.user_id == user.id))).unique().scalars().all()
    drafts = (await session.execute(select(OutreachDraft).where(OutreachDraft.user_id == user.id))).unique().scalars().all()
    runs = (await session.execute(select(AgentRun).where(AgentRun.user_id == user.id))).scalars().all()
    questions = (await session.execute(select(SkillQuestion).where(SkillQuestion.user_id == user.id))).scalars().all()
    notes = (await session.execute(select(Notification).where(Notification.user_id == user.id))).scalars().all()
    consents = (await session.execute(select(Consent).where(Consent.user_id == user.id))).scalars().all()
    requests = (await session.execute(select(RightsRequest).where(RightsRequest.user_id == user.id))).scalars().all()
    mail = await session.get(MailAccount, user.id)
    data = {
        "exported_at": datetime.now(UTC).isoformat(),
        "account": {"email": user.email, "name": user.name, "plan": user.plan, "created_at": user.created_at.isoformat()},
        "profile": {
            "resume_filename": profile.resume_filename if profile else None,
            "resume_text": profile.resume_text if profile else "",
            "resume": profile.resume if profile else {},
            "preferences": profile.preferences if profile else {},
            "research": profile.research if profile else {},
        },
        "matches": [
            {
                "job": {"title": m.job.title, "company": m.job.company, "location": m.job.location, "url": m.job.url},
                "score": m.score, "stage": m.stage, "explanation": m.explanation, "notes": m.notes,
                "applied_at": m.applied_at.isoformat() if m.applied_at else None, "created_at": m.created_at.isoformat(),
            }
            for m in matches
        ],
        "drafts": [
            {"subject": d.subject, "email_body": d.email_body, "linkedin_note": d.linkedin_note, "to_email": d.to_email, "status": d.status,
             "sent_at": d.sent_at.isoformat() if d.sent_at else None}
            for d in drafts
        ],
        "skill_answers": [{"skill": q.skill, "status": q.status, "answer": q.answer} for q in questions],
        "runs": [{"trigger": r.trigger, "status": r.status, "created_at": r.created_at.isoformat(), "stats": r.stats} for r in runs],
        "notifications": [{"title": n.title, "body": n.body, "created_at": n.created_at.isoformat()} for n in notes],
        "consents": [
            {"purpose": c.purpose, "notice_version": c.notice_version, "method": c.method, "granted_at": c.granted_at.isoformat(),
             "withdrawn_at": c.withdrawn_at.isoformat() if c.withdrawn_at else None}
            for c in consents
        ],
        "rights_requests": [
            {"kind": r.kind, "details": r.details, "status": r.status, "response": r.response, "created_at": r.created_at.isoformat(), "due_at": r.due_at.isoformat()}
            for r in requests
        ],
        # Connection details only: the credential itself is never exported.
        "mail_account": {"provider": mail.provider, "from_email": mail.from_email, "connected_at": mail.verified_at.isoformat() if mail.verified_at else None} if mail else None,
        "age_confirmed_at": user.adult_confirmed_at.isoformat() if user.adult_confirmed_at else None,
    }
    return JSONResponse(data, headers={"Content-Disposition": 'attachment; filename="jobpilot-export.json"'})


@router.delete("/account", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account(request: Request, response: Response, user: UserDep, session: SessionDep) -> None:
    """Deletes the account and everything in it (resume, matches, drafts, runs, mail connection)."""
    if not user.is_demo:
        body = await request.json() if request.headers.get("content-length", "0") != "0" else {}
        if not verify_password(str(body.get("password", "")), user.password_hash):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Enter your password to delete your account")
    await session.execute(delete(User).where(User.id == user.id))  # every table cascades from users
    await session.commit()
    response.delete_cookie(COOKIE_NAME, path="/")

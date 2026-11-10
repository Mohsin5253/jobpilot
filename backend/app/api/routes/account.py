"""Your account: your own outgoing mailbox, plan & usage, data export and deletion."""

import smtplib
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy import delete, select

from app.api.deps import RealUserDep, SessionDep, UserDep
from app.models import AgentRun, JobMatch, MailAccount, Notification, OutreachDraft, Profile, SkillQuestion, User
from app.schemas import MailAccountIn, MailAccountOut
from app.security import COOKIE_NAME, encrypt_secret, verify_password
from app.services.mailer import Sender, verify_login
from app.services.ratelimit import hit
from app.services.usage import usage_today

router = APIRouter(tags=["account"])


def _mail_out(acct: MailAccount | None) -> MailAccountOut:
    if acct is None:
        return MailAccountOut(connected=False)
    return MailAccountOut(
        connected=True, host=acct.host, port=acct.port, from_email=acct.from_email, from_name=acct.from_name, verified_at=acct.verified_at
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
    acct.host, acct.port, acct.username, acct.from_email = sender.host, sender.port, str(body.username), str(body.username)
    acct.from_name = sender.from_name
    acct.password_enc = encrypt_secret(password)
    acct.verified_at = datetime.now(UTC)
    session.add(acct)
    await session.commit()
    return _mail_out(acct)


@router.delete("/mail-account", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect_mail_account(user: UserDep, session: SessionDep) -> None:
    await session.execute(delete(MailAccount).where(MailAccount.user_id == user.id))
    await session.commit()


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

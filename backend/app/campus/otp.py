"""One-time codes by email (institutional email checks, TPO / Principal 2FA, roster claims) and lockouts for repeated
wrong staff codes. Codes are 6 digits, stored only as a keyed hash, valid 10 minutes, 5 tries each."""

import hashlib
import hmac
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import select, text

from app.campus.ids import uuid7
from app.config import settings
from app.db import session_scope
from app.services.scam_shield import FREE_MAIL

PERSONAL_DOMAINS = FREE_MAIL | {"rediff.com", "outlook.in", "hotmail.co.in", "yahoo.co.uk", "msn.com", "me.com", "mac.com", "tutanota.com", "yandex.com", "mail.ru", "gmx.de"}
TTL = timedelta(minutes=10)
MAX_TRIES = 5
LOCK_AFTER = 5  # wrong staff codes ...
LOCK_FOR = timedelta(minutes=15)  # ... locks the account and the network address for this long


def _h(code: str, salt: str) -> str:
    return hmac.new(settings.jwt_secret.encode(), f"{salt}:{code}".encode(), hashlib.sha256).hexdigest()


def personal(email: str) -> bool:
    return email.rsplit("@", 1)[-1].lower() in PERSONAL_DOMAINS


def domain_allowed(email: str, allowed: list[str]) -> bool:
    d = email.rsplit("@", 1)[-1].lower()
    return any(d == a.lower().lstrip("@") or d.endswith("." + a.lower().lstrip("@")) for a in allowed or [])


async def send(email: str, subject: str, body: str) -> bool:
    from app.services.mailer import send_system_email

    return await send_system_email(email, subject, body)


async def issue(user_id: uuid.UUID, email: str, purpose: str, campus_id: uuid.UUID | None = None, department_id: uuid.UUID | None = None) -> None:
    code = f"{secrets.randbelow(1_000_000):06d}"
    async with session_scope() as s:
        await s.execute(text("UPDATE email_otps SET used_at = now() WHERE user_id = :u AND purpose = :p AND used_at IS NULL"), {"u": user_id, "p": purpose})
        from app.campus.models import EmailOtp

        s.add(EmailOtp(id=uuid7(), user_id=user_id, email=email.lower(), purpose=purpose, campus_id=campus_id, department_id=department_id, code_hash=_h(code, f"{user_id}:{purpose}"), expires_at=datetime.now(UTC) + TTL))
    sent = await send(email, "Your JobPilot code", f"Your code is {code}. It expires in 10 minutes. If you didn't ask for it, ignore this email.")
    if not sent:
        raise HTTPException(503, "Email isn't set up on this server yet, so the code couldn't be sent")


async def check(user_id: uuid.UUID, purpose: str, code: str):
    """The verified code row (email, campus) or a 422."""
    from app.campus.models import EmailOtp

    async with session_scope() as s:
        row = (
            await s.execute(select(EmailOtp).where(EmailOtp.user_id == user_id, EmailOtp.purpose == purpose, EmailOtp.used_at.is_(None)).order_by(EmailOtp.created_at.desc()).limit(1).with_for_update())
        ).scalar_one_or_none()
        if row is None or row.expires_at < datetime.now(UTC) or row.attempts >= MAX_TRIES:
            raise HTTPException(422, "That code has expired. Ask for a new one.")
        if not hmac.compare_digest(row.code_hash, _h(code.strip(), f"{user_id}:{purpose}")):
            row.attempts += 1
            await s.commit()
            raise HTTPException(422, f"That code is wrong ({MAX_TRIES - row.attempts} tries left)")
        row.used_at = datetime.now(UTC)
        return row


# ---------- staff-code lockout (security, so it works even when general rate limits are off) ----------


async def _fails(key: str) -> int:
    async with session_scope() as s:
        return int((await s.execute(text("SELECT coalesce(sum(count), 0) FROM rate_limits WHERE key = :k AND window_start > :t"), {"k": key, "t": datetime.now(UTC) - LOCK_FOR})).scalar_one())


async def locked(user_id: uuid.UUID, ip: str) -> bool:
    return await _fails(f"staffcode:u:{user_id}") >= LOCK_AFTER or await _fails(f"staffcode:ip:{ip}") >= LOCK_AFTER * 4


async def record_failure(user_id: uuid.UUID, ip: str) -> None:
    now = datetime.now(UTC).replace(second=0, microsecond=0)
    async with session_scope() as s:
        for k in (f"staffcode:u:{user_id}", f"staffcode:ip:{ip}"):
            await s.execute(
                text("INSERT INTO rate_limits (key, window_start, count) VALUES (:k, :w, 1) ON CONFLICT (key, window_start) DO UPDATE SET count = rate_limits.count + 1"),
                {"k": k, "w": now},
            )

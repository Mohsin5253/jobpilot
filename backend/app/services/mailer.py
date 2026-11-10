"""Outgoing mail.

* Applications go out from the user's own mailbox (their MailAccount: e.g. Gmail with an app password),
  never from a shared address. Without one, approving a draft opens it in the user's mail app instead.
* System mail (password resets, new-match alerts) uses the service's own SMTP settings (SMTP_*).
"""

import asyncio
import smtplib
import uuid
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr

from sqlalchemy import select

from app.config import settings
from app.db import session_scope
from app.logging import log
from app.models import MailAccount
from app.security import decrypt_secret

Attachment = tuple[str, bytes, str]  # (filename, content, mime type)


@dataclass
class Sender:
    host: str
    port: int
    username: str | None
    password: str | None
    from_email: str
    from_name: str = ""


class MailNotConnected(RuntimeError):
    pass


def system_sender() -> Sender | None:
    if not settings.smtp_enabled:
        return None
    return Sender(settings.smtp_host or "", settings.smtp_port, settings.smtp_user, settings.smtp_password, settings.smtp_from or "", "JobPilot")


async def user_sender(user_id: uuid.UUID) -> Sender | None:
    async with session_scope() as s:
        acct = (await s.execute(select(MailAccount).where(MailAccount.user_id == user_id))).scalar_one_or_none()
    if acct is None:
        return None
    password = decrypt_secret(acct.password_enc)
    if password is None:  # the encryption key changed: the user has to reconnect
        log.warning("mail.undecryptable", user_id=str(user_id))
        return None
    return Sender(acct.host, acct.port, acct.username, password, acct.from_email, acct.from_name)


def _connect(sender: Sender) -> smtplib.SMTP:
    if sender.port == 465:
        smtp: smtplib.SMTP = smtplib.SMTP_SSL(sender.host, sender.port, timeout=30)
    else:
        smtp = smtplib.SMTP(sender.host, sender.port, timeout=30)
        smtp.starttls()
    if sender.username:
        smtp.login(sender.username, sender.password or "")
    return smtp


def _verify_sync(sender: Sender) -> None:
    with _connect(sender):
        pass


async def verify_login(sender: Sender) -> None:
    """Log in and out without sending anything; raises smtplib.SMTPException / OSError on failure."""
    await asyncio.to_thread(_verify_sync, sender)


def _send_sync(sender: Sender, to: str, subject: str, body: str, reply_to: str | None, attachments: list[Attachment], cc: str | None) -> None:
    msg = EmailMessage()
    msg["From"] = formataddr((sender.from_name, sender.from_email)) if sender.from_name else sender.from_email
    msg["To"] = to
    if cc:
        msg["Cc"] = cc
    msg["Subject"] = subject
    if reply_to:
        msg["Reply-To"] = reply_to
    msg.set_content(body)
    for name, content, mime in attachments:
        maintype, subtype = mime.split("/", 1)
        msg.add_attachment(content, maintype=maintype, subtype=subtype, filename=name)
    with _connect(sender) as smtp:
        smtp.send_message(msg)


async def send_email(
    to: str, subject: str, body: str, *, sender: Sender, reply_to: str | None = None, attachments: list[Attachment] | None = None, cc: str | None = None
) -> None:
    await asyncio.to_thread(_send_sync, sender, to, subject, body, reply_to, attachments or [], cc)


async def send_as_user(user_id: uuid.UUID, to: str, subject: str, body: str, **kw) -> Sender:
    """Send from the user's own mailbox. Raises MailNotConnected when they haven't connected one."""
    sender = await user_sender(user_id)
    if sender is None:
        raise MailNotConnected("Connect your email in Settings to send from your own address.")
    await send_email(to, subject, body, sender=sender, **kw)
    return sender


async def send_system_email(to: str, subject: str, body: str) -> bool:
    sender = system_sender()
    if sender is None:
        return False
    try:
        await send_email(to, subject, body, sender=sender)
        return True
    except (smtplib.SMTPException, OSError) as exc:
        log.warning("mail.system_failed", error=str(exc)[:200])
        return False

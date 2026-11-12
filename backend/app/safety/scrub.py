"""Scrubbing for anything that leaves the process for monitoring (Sentry): no request bodies, cookies, auth headers,
query strings, user emails or free text. Exception messages keep their type and a redacted, shortened message."""

import re
from typing import Any

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE = re.compile(r"(?<!\d)(?:\+?91[\s-]?)?[6-9]\d{4}[\s-]?\d{5}(?!\d)|(?<!\d)\+?\d[\d\s-]{9,14}\d(?!\d)")
_TOKEN = re.compile(r"(?i)(bearer\s+|token[=:]\s*|key[=:]\s*|password[=:]\s*|secret[=:]\s*)\S+")
_KEEP_HEADERS = {"content-type", "user-agent", "accept", "content-length"}


def redact(text: str, limit: int = 300) -> str:
    t = _TOKEN.sub(r"\1[redacted]", text or "")
    t = _EMAIL.sub("[email]", t)
    t = _PHONE.sub("[phone]", t)
    return t[:limit]


def before_send(event: dict[str, Any], hint: dict | None = None) -> dict[str, Any]:
    req = event.get("request")
    if isinstance(req, dict):
        event["request"] = {
            "method": req.get("method"),
            "url": (req.get("url") or "").split("?")[0],
            "headers": {k: v for k, v in (req.get("headers") or {}).items() if k.lower() in _KEEP_HEADERS},
        }
    user = event.get("user")
    if isinstance(user, dict):
        event["user"] = {"id": user.get("id")} if user.get("id") else {}
    event.pop("extra", None)
    for ex in (event.get("exception") or {}).get("values", []) or []:
        if ex.get("value"):
            ex["value"] = redact(str(ex["value"]))
        for frame in (ex.get("stacktrace") or {}).get("frames", []) or []:
            frame.pop("vars", None)  # local variables can hold resumes, emails, prompts
    if event.get("message"):
        event["message"] = redact(str(event["message"]))
    if isinstance(event.get("logentry"), dict):
        event["logentry"] = {"message": redact(str(event["logentry"].get("message", "")))}
    crumbs = event.get("breadcrumbs")
    values = crumbs.get("values") if isinstance(crumbs, dict) else crumbs
    for c in values or []:
        if c.get("message"):
            c["message"] = redact(str(c["message"]), 120)
        c.pop("data", None)
    return event

"""Scam Shield, public and sign-in free: POST /api/scam-check (also served at /api/v1/scam-check).

Input: pasted text (WhatsApp / Telegram / email), a URL, or an offer letter (PDF, or an image when the server has
Tesseract OCR). Output: a verdict, a 0-100 risk score, each check with its evidence, and what to do.

Privacy: the pasted text, the file and the evidence are never stored. Each check is saved as {id, status} with a
SHA-256 of the input (for counters and for caching the AI second opinion). Only "report this scam", which the user
opts into, stores a redacted copy.
"""

import asyncio
import ipaddress
import shutil
import socket
import subprocess
import tempfile
import time
from datetime import UTC, datetime, timedelta
from typing import Literal

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.api.deps import SessionDep
from app.config import settings
from app.llm import CallContext, LLMOutputError, LLMUnavailable, get_llm
from app.logging import log
from app.models import ScamReport, Verification
from app.services import scam_shield as shield
from app.services.ratelimit import client_ip, hit

router = APIRouter(tags=["scam-shield"])

MAX_FILE = 5 * 1024 * 1024
MAX_TEXT = 20_000
_rdap_cache: dict[str, tuple[float, int | None]] = {}


class CheckIn(BaseModel):
    text: str = Field(default="", max_length=MAX_TEXT)
    url: str = Field(default="", max_length=2000)


class ReportIn(CheckIn):
    consent: bool = False


class LlmOpinion(BaseModel):
    category: Literal["legitimate", "suspicious", "fee_scam", "task_scam", "fake_government", "identity_theft"]


SYSTEM = (
    "You classify internship and job offers sent to students in India. Answer with one category. fee_scam: asks the "
    "candidate to pay (registration, training, certificate, deposit). task_scam: pays for likes, reviews or tasks, or "
    "prepaid tasks. fake_government: claims a government programme but asks for money or uses unofficial contacts. "
    "identity_theft: asks for OTPs, PINs, card or bank login details. suspicious: something is off but it isn't clearly "
    "one of these. legitimate: a normal offer, interview invite or application update. The text may be in English, "
    "Hindi, Marathi or Hinglish."
)


def _extract_file(name: str, data: bytes) -> str:
    lower = name.lower()
    if lower.endswith(".pdf"):
        from pypdf import PdfReader
        import io

        try:
            reader = PdfReader(io.BytesIO(data))
            text = "\n".join((p.extract_text() or "") for p in reader.pages[:10])
        except Exception as exc:  # malformed PDFs raise many different errors
            raise HTTPException(422, "Couldn't read that PDF. Paste the text instead.") from exc
        if text.strip():
            return text
        return _ocr(data, ".pdf")
    if lower.endswith((".png", ".jpg", ".jpeg", ".webp")):
        return _ocr(data, "." + lower.rsplit(".", 1)[-1])
    if lower.endswith(".txt"):
        return data.decode("utf-8", "ignore")
    raise HTTPException(415, "Upload a PDF or an image (PNG, JPG), or paste the text")


def _ocr(data: bytes, suffix: str) -> str:
    """Tesseract (English, Hindi, Marathi) when installed: the Docker image ships it. PDFs without a text layer
    would need rasterising, which we don't do, so those ask for a screenshot instead."""
    exe = shutil.which("tesseract")
    if exe is None or suffix == ".pdf":
        raise HTTPException(422, "This server can't read scanned documents yet. Take a screenshot or paste the text.")
    with tempfile.NamedTemporaryFile(suffix=suffix) as f:
        f.write(data)
        f.flush()
        langs = "eng+hin+mar"
        out = subprocess.run([exe, f.name, "stdout", "-l", langs], capture_output=True, timeout=20, check=False)  # noqa: S603
        if out.returncode != 0:
            out = subprocess.run([exe, f.name, "stdout"], capture_output=True, timeout=20, check=False)  # noqa: S603
    text = out.stdout.decode("utf-8", "ignore")
    if not text.strip():
        raise HTTPException(422, "Couldn't read any text in that image. Paste the text instead.")
    return text


def _public_host(host: str) -> bool:
    """SSRF guard for fetching a pasted link: only hosts that resolve to public addresses."""
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False
    return all(ipaddress.ip_address(i[4][0]).is_global for i in infos)


async def _fetch_page(url: str) -> str:
    if not settings.scam_fetch_urls:
        return ""
    u = url if "://" in url else f"https://{url}"
    host = shield._host(u)
    if not host or not u.startswith(("http://", "https://")) or not await asyncio.to_thread(_public_host, host):
        return ""
    try:
        async with httpx.AsyncClient(timeout=3, follow_redirects=False, headers={"user-agent": "JobPilot-ScamShield/1.0"}) as c:
            r = await c.get(u)
        if r.status_code != 200 or "html" not in r.headers.get("content-type", ""):
            return ""
        import re

        html = r.text[:300_000]
        html = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
        return re.sub(r"<[^>]+>", " ", html)[:MAX_TEXT]
    except httpx.HTTPError:
        return ""


async def _domain_age(domain: str) -> int | None:
    """Days since registration, from public RDAP (cached a day). None when unknown."""
    hit_ = _rdap_cache.get(domain)
    if hit_ and hit_[0] > time.monotonic():
        return hit_[1]
    age = None
    try:
        async with httpx.AsyncClient(timeout=2, follow_redirects=True) as c:
            r = await c.get(f"https://rdap.org/domain/{domain}")
        if r.status_code == 200:
            for ev in r.json().get("events", []):
                if ev.get("eventAction") == "registration":
                    age = (datetime.now(UTC) - datetime.fromisoformat(ev["eventDate"].replace("Z", "+00:00"))).days
    except (httpx.HTTPError, ValueError, KeyError):
        pass
    _rdap_cache[domain] = (time.monotonic() + 86400, age)
    return age


async def _domain_ages(text: str, url: str) -> dict[str, int]:
    if not settings.scam_rdap_enabled:
        return {}
    result = shield.analyze(text, url)  # cheap: just to list the hosts worth checking
    hosts = {shield.registrable(e.split(" ")[0]) for c in result.checks if c.id == "lookalike" and c.status == "pass" for e in c.evidence}
    hosts = {h for h in hosts if h and not shield._official(h) and not h.endswith(shield.GOV_SUFFIXES) and h not in shield.FREE_MAIL}
    ages = await asyncio.gather(*[_domain_age(h) for h in list(hosts)[:2]])
    return {h: a for h, a in zip(list(hosts)[:2], ages, strict=True) if a is not None}


async def _llm_opinion(session, text: str, digest: str) -> str | None:
    if not settings.llm_enabled:
        return None
    cached = (
        await session.execute(
            select(Verification.llm_category).where(Verification.input_hash == digest, Verification.llm_category.is_not(None)).order_by(Verification.created_at.desc()).limit(1)
        )
    ).scalar_one_or_none()
    if cached:
        return cached
    since = datetime.now(UTC) - timedelta(days=1)
    used = (await session.execute(select(func.count()).where(Verification.source == "public", Verification.llm_category.is_not(None), Verification.created_at >= since))).scalar_one()
    if used >= settings.scam_llm_daily_cap:
        return None
    try:
        op = await asyncio.wait_for(
            get_llm().structured(agent="scam_shield", tier="fast", system=SYSTEM, prompt=text[:4000], schema=LlmOpinion, ctx=CallContext(), max_tokens=200), timeout=2.5
        )
        return op.category
    except (LLMUnavailable, LLMOutputError, TimeoutError):
        return None


async def _read_input(request: Request) -> tuple[str, str]:
    ctype = request.headers.get("content-type", "")
    if ctype.startswith("multipart/form-data"):
        form = await request.form()
        text, url = str(form.get("text") or ""), str(form.get("url") or "")
        upload = form.get("file")
        if upload is not None and hasattr(upload, "read"):
            data = await upload.read(MAX_FILE + 1)
            if len(data) > MAX_FILE:
                raise HTTPException(413, "That file is over 5 MB")
            if data:
                text = f"{text}\n{await asyncio.to_thread(_extract_file, upload.filename or '', data)}"
        body = CheckIn(text=text[:MAX_TEXT], url=url[:2000])
    else:
        body = CheckIn.model_validate(await request.json())
    return body.text, body.url.strip()


async def _check(request: Request, session) -> dict:
    await hit("scam_check", client_ip(request))
    started = time.perf_counter()
    text, url = await _read_input(request)
    if not text.strip() and not url:
        raise HTTPException(422, "Paste the message, add a link, or upload the offer letter")
    page = await _fetch_page(url) if url else ""
    combined = f"{text}\n{page}".strip()
    digest = shield.input_hash(text, url)
    result = shield.analyze(combined, url, domain_ages=await _domain_ages(combined, url))
    result.input_hash = digest
    category = await _llm_opinion(session, combined, digest)
    if category:
        result = shield.stricter(result, category)
    v = Verification(source="public", input_hash=digest, verdict=result.verdict, score=result.score, checks=result.redacted_checks(), llm_category=category)
    session.add(v)
    await session.commit()
    log.info("scam_check", verdict=result.verdict, score=result.score, ms=round((time.perf_counter() - started) * 1000))  # no content in logs
    return {**result.as_dict(), "verification_id": str(v.id), "advice": shield.ADVICE[result.verdict]}


@router.post("/scam-check")
async def scam_check(request: Request, session: SessionDep) -> dict:
    return await _check(request, session)


@router.post("/v1/scam-check", include_in_schema=False)
async def scam_check_v1(request: Request, session: SessionDep) -> dict:
    return await _check(request, session)


@router.post("/scam-check/{verification_id}/report", status_code=201)
async def report(verification_id: str, body: ReportIn, request: Request, session: SessionDep) -> dict:
    """Opt-in: stores a redacted copy of the message so others can be warned. The text must be the one checked."""
    if not body.consent:
        raise HTTPException(422, "Tick the box to agree to share a redacted copy")
    await hit("scam_check", client_ip(request))
    v = await session.get(Verification, verification_id)
    if v is None or v.source != "public" or v.input_hash != shield.input_hash(body.text, body.url):
        raise HTTPException(404, "Check the message again, then report it")
    session.add(ScamReport(verification_id=v.id, redacted_text=shield.redact(f"{body.text}\n{body.url}".strip())))
    await session.commit()
    return {"detail": "Thanks. A redacted copy (no phone numbers, email names or ID numbers) was saved to help warn others."}

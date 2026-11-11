"""Speech-to-text for spoken interview answers: Whisper large-v3-turbo on Groq.

The browser's live recognition shows words as the student speaks; when they stop, the recording comes here and the
Whisper transcript replaces it. Whisper is far more accurate for Indian English and technical vocabulary, and the
question being answered is passed as a hint so terms like "PostgreSQL" or "ROAS" come out right.
The audio is sent to Groq for transcription only: it is never stored by JobPilot, and only the text is kept (as the
answer the student submits).
"""

import re

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.api.deps import RealUserDep, UserDep
from app.config import settings
from app.logging import log
from app.services.ratelimit import hit
from app.skills import extract_skills

router = APIRouter(tags=["speech"])

MODEL = "whisper-large-v3-turbo"
MAX_BYTES = 12 * 1024 * 1024  # about 10 minutes of compressed audio; answers are a few minutes at most
AUDIO_TYPES = ("audio/webm", "audio/ogg", "audio/mp4", "audio/mpeg", "audio/wav", "audio/x-wav", "audio/aac", "video/webm")


# Spoken-English mishearings of technical terms, and spellings Whisper often gets almost right.
FIXES = {
    r"\bjit ?hub\b": "GitHub", r"\bgit ?hub\b": "GitHub", r"\bgit ?lab\b": "GitLab", r"\bci[- ]cd\b": "CI/CD",
    r"\bpost ?gre ?sql\b": "PostgreSQL", r"\bpost ?gres\b": "Postgres", r"\bmy ?sql\b": "MySQL", r"\bno ?sql\b": "NoSQL",
    r"\bjava ?script\b": "JavaScript", r"\btype ?script\b": "TypeScript", r"\bnode ?(?:\.|dot)? ?js\b": "Node.js",
    r"\bnext ?(?:\.|dot)? ?js\b": "Next.js", r"\breact ?(?:\.|dot)? ?js\b": "React", r"\bfast ?api\b": "FastAPI",
    r"\bpy ?torch\b": "PyTorch", r"\btensor ?flow\b": "TensorFlow", r"\bscikit[- ]?learn\b": "scikit-learn", r"\bnum ?py\b": "NumPy",
    r"\bpower ?bi\b": "Power BI", r"\bk8s\b": "Kubernetes", r"\bkuber ?netes\b": "Kubernetes", r"\bdev ?ops\b": "DevOps",
    r"\bml ?ops\b": "MLOps", r"\bllms\b": "LLMs", r"\bllm\b": "LLM", r"\brest ?apis?\b": lambda m: "REST APIs" if m.group(0).lower().endswith("s") else "REST API",
    r"\bjson\b": "JSON", r"\bsql\b": "SQL", r"\baws\b": "AWS", r"\bgcp\b": "GCP", r"\bdsa\b": "DSA", r"\boop\b": "OOP",
    r"\bui ?/? ?ux\b": "UI/UX", r"\bseo\b": "SEO", r"\broas\b": "ROAS", r"\bctr\b": "CTR", r"\bkpis?\b": lambda m: m.group(0).upper().replace("KPIS", "KPIs"),
    r"\bgst\b": "GST", r"\btds\b": "TDS", r"\bdcf\b": "DCF", r"\bcgpa\b": "CGPA", r"\bb\. ?tech\b": "B.Tech",
}
_FIXES = [(re.compile(k, re.I), v) for k, v in FIXES.items()]


def polish(text: str) -> str:
    """Correct technical terms' spelling and casing (GitHub, PostgreSQL, CI/CD...), which matter in an interview answer."""
    for rx, rep in _FIXES:
        text = rx.sub(rep, text)
    return text


def vocabulary(hint: str) -> str:
    """Canonical spellings of the technical terms in play, so Whisper writes them correctly in the first place."""
    terms = extract_skills(hint)
    return ", ".join(dict.fromkeys([*terms, *(t for t in ("GitHub", "CI/CD", "PostgreSQL", "REST API") if t.lower() in hint.lower())]))[:300]


def enabled() -> bool:
    return bool(settings.groq_api_key)


@router.get("/stt/status")
async def status(user: UserDep) -> dict:
    return {"enabled": enabled(), "model": MODEL if enabled() else None}


@router.post("/stt")
async def transcribe(user: RealUserDep, audio: UploadFile = File(...), hint: str = Form(default="", max_length=600)) -> dict:
    if not enabled():
        raise HTTPException(503, "Accurate speech-to-text isn't configured on this server (it needs GROQ_API_KEY). Live browser recognition still works.")
    await hit("stt", str(user.id))
    kind = (audio.content_type or "").split(";")[0].strip()
    if kind not in AUDIO_TYPES:
        raise HTTPException(415, "Unsupported audio format")
    data = await audio.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise HTTPException(413, "That recording is too long. Answer in shorter parts.")
    if len(data) < 800:
        return {"text": "", "model": MODEL}
    import groq

    ext = {"audio/mp4": "m4a", "audio/mpeg": "mp3", "audio/wav": "wav", "audio/x-wav": "wav", "audio/aac": "aac", "audio/ogg": "ogg"}.get(kind, "webm")
    try:
        client = groq.AsyncGroq(api_key=settings.groq_api_key, max_retries=2, timeout=60.0)
        res = await client.audio.transcriptions.create(
            file=(f"answer.{ext}", data),
            model=MODEL,
            language="en",
            temperature=0,
            response_format="json",
            # Whisper uses the prompt as context: the question's own words make domain terms come out right.
            prompt=("Interview answer by an Indian student. Technical terms: " + vocabulary(hint) + ". " + hint)[:800],
        )
    except (groq.APIStatusError, groq.APIConnectionError) as exc:
        log.warning("stt.failed", error=type(exc).__name__)
        raise HTTPException(502, "Transcription failed. Your live transcript is kept.") from exc
    text = polish((getattr(res, "text", "") or "").strip())
    return {"text": text, "model": MODEL}

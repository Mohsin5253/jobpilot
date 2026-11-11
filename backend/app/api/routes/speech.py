"""Speech-to-text for spoken interview answers: Whisper large-v3 on Groq (the full model, the most accurate one).

The browser's live recognition shows words as the student speaks; when they stop, the recording comes here and the
Whisper transcript replaces it. Whisper is far more accurate for Indian English and technical vocabulary; the technical
terms in the question are passed as vocabulary so "PostgreSQL" or "ROAS" come out right, and the prompt is written in
spoken style so Whisper keeps the student's exact words instead of tidying them. Segments Whisper itself marks as
probably not speech (its known "Thank you." on silence) are dropped.
The audio is sent to Groq for transcription only: it is never stored by JobPilot, and only the text is kept (as the
answer the student submits).
"""

import re

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.api.deps import RealUserDep, SessionDep, UserDep
from app.config import settings
from app.logging import log
from app.services.ratelimit import hit
from app.skills import extract_skills

router = APIRouter(tags=["speech"])

MODEL = settings.stt_model
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
    r"\bci ?/? ?cd\b|\bc ?i ?c ?d\b": "CI/CD", r"\bpost ?gres ?(?:cal|kel|kwel|sequel|q ?l|s ?q ?l)\b": "PostgreSQL",
    r"\bmy ?sequel\b": "MySQL", r"\bmongo ?db\b": "MongoDB", r"\bfire ?base\b": "Firebase", r"\bgraph ?ql\b": "GraphQL",
    r"\bc ?sharp\b": "C#", r"\bc ?plus ?plus\b": "C++", r"\bdot ?net\b": ".NET", r"\bexpress ?(?:\.|dot)? ?js\b": "Express.js",
    r"\bspring ?boot\b": "Spring Boot", r"\btail ?wind\b": "Tailwind", r"\bopen ?ai\b": "OpenAI", r"\blang ?chain\b": "LangChain",
    r"\bhugging ?face\b": "Hugging Face", r"\bmat ?plot ?lib\b": "Matplotlib", r"\bjupiter notebook\b": "Jupyter notebook",
    r"\btablo\b": "Tableau", r"\bfig ?ma\b": "Figma", r"\bj ?query\b": "jQuery", r"\bvs ?code\b": "VS Code",
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
    return ", ".join(dict.fromkeys([*terms, *(t for t in ("GitHub", "CI/CD", "PostgreSQL", "REST API") if t.lower() in hint.lower())]))[:400]


# What Whisper writes for silence or noise; never a real answer on its own.
_PHANTOM = re.compile(r"^\W*(thank you|thanks for watching|thank you for watching|you|bye|okay|subtitles by.*|\.)\W*$", re.I)


def keep_speech(res) -> str:
    """The transcript without the segments Whisper marks as unlikely speech (silence, noise, repetition loops)."""
    segments = getattr(res, "segments", None) or (res.get("segments") if isinstance(res, dict) else None)
    text = (getattr(res, "text", None) if not isinstance(res, dict) else res.get("text")) or ""
    if not segments:
        return "" if _PHANTOM.match(text.strip()) else text.strip()
    kept = []
    for seg in segments:
        g = seg if isinstance(seg, dict) else seg.__dict__
        silent = (g.get("no_speech_prob") or 0) > 0.6 and (g.get("avg_logprob") or 0) < -0.8
        looping = (g.get("compression_ratio") or 0) > 2.6
        t = (g.get("text") or "").strip()
        if t and not silent and not looping and not _PHANTOM.match(t):
            kept.append(t)
    return re.sub(r"\s+", " ", " ".join(kept)).strip()


def prompt_for(hint: str) -> str:
    """Spoken-style context: Whisper copies the prompt's style, so a natural, unpolished sentence keeps the speaker's
    own wording (repetitions and all) and the vocabulary list fixes the spelling of technical terms. The question
    itself isn't included: Whisper can echo prompt text into the transcript."""
    vocab = vocabulary(hint)
    return ("So, um, I'll answer in my own words. I worked with " + (vocab or "Python, SQL and Git") + ", and, uh, I'll explain what I did.")[:600]


def enabled() -> bool:
    return bool(settings.groq_api_key)


@router.get("/stt/status")
async def status(user: UserDep) -> dict:
    return {"enabled": enabled(), "model": MODEL if enabled() else None}


@router.post("/stt")
async def transcribe(user: RealUserDep, session: SessionDep, audio: UploadFile = File(...), hint: str = Form(default="", max_length=600)) -> dict:
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
    from sqlalchemy import select

    from app.models import Profile

    # The student's own skills join the vocabulary: answers are mostly about what they've built and used.
    resume = (await session.execute(select(Profile.resume).where(Profile.user_id == user.id))).scalar_one_or_none() or {}
    hint = f"{hint} {', '.join((resume.get('skills') or [])[:30])}"
    ext = {"audio/mp4": "m4a", "audio/mpeg": "mp3", "audio/wav": "wav", "audio/x-wav": "wav", "audio/aac": "aac", "audio/ogg": "ogg"}.get(kind, "webm")
    try:
        client = groq.AsyncGroq(api_key=settings.groq_api_key, max_retries=2, timeout=60.0)
        res = await client.audio.transcriptions.create(
            file=(f"answer.{ext}", data),
            model=MODEL,
            language="en",
            temperature=0,
            response_format="verbose_json",
            prompt=prompt_for(hint),
        )
    except (groq.APIStatusError, groq.APIConnectionError) as exc:
        log.warning("stt.failed", error=type(exc).__name__)
        raise HTTPException(502, "Transcription failed. Your live transcript is kept.") from exc
    text = polish(keep_speech(res))
    return {"text": text, "model": MODEL}

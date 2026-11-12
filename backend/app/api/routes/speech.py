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
from pydantic import BaseModel, Field

from app.api.deps import RealUserDep, SessionDep, UserDep
from app.config import settings
from app.services.ratelimit import hit
from app.skills import extract_skills

router = APIRouter(tags=["speech"])

MODEL = settings.stt_model
MAX_BYTES = 12 * 1024 * 1024  # about 10 minutes of compressed audio; answers are a few minutes at most
AUDIO_TYPES = ("audio/webm", "audio/ogg", "audio/mp4", "audio/mpeg", "audio/wav", "audio/x-wav", "audio/aac", "video/webm")


from app.dictation.terms import FIXES, polish  # noqa: F401  (re-exported for callers and tests)


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


class Around(BaseModel):
    """What the interview shows around the cursor (Flowtype's context collector, for the answer box)."""

    before: str = ""
    after: str = ""
    company: str = ""
    role: str = ""
    round_name: str = ""
    kind: str = ""


def _around(before: str, after: str, company: str, role: str, round_name: str, kind: str) -> Around:
    return Around(before=before, after=after, company=company, role=role, round_name=round_name, kind=kind)


async def _read_audio(audio: UploadFile | None) -> tuple[bytes, str]:
    if audio is None:
        return b"", "webm"
    kind = (audio.content_type or "").split(";")[0].strip()
    if kind not in AUDIO_TYPES:
        raise HTTPException(415, "Unsupported audio format")
    data = await audio.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise HTTPException(413, "That recording is too long. Answer in shorter parts.")
    ext = {"audio/mp4": "m4a", "audio/mpeg": "mp3", "audio/wav": "wav", "audio/x-wav": "wav", "audio/aac": "aac", "audio/ogg": "ogg"}.get(kind, "webm")
    return (data if len(data) >= 800 else b""), ext


async def _context(session, user, hint: str, around: Around, prefix: str = ""):
    """Your own words (name, college, employers, projects, skills, the words you added and the ones learned from your
    corrections), the question's terms and the answer around the cursor."""
    from sqlalchemy import select

    from app.dictation.context import collect
    from app.dictation.pipeline import DictationContext
    from app.models import Profile
    from app.schemas import ResumeData
    from app.services.speech_vocab import personal_vocabulary

    p = (await session.execute(select(Profile).where(Profile.user_id == user.id))).scalar_one_or_none()
    resume = ResumeData.model_validate((p.resume if p else None) or {})
    prefs = (p.preferences if p else None) or {}
    mine = list(prefs.get("speech_words") or [])
    learned = list(prefs.get("speech_learned") or [])
    dictionary = personal_vocabulary(resume, (p.academics if p else None) or {}, learned, own_name=user.name or "")
    context = re.findall(r"\bat ([A-Z][\w&.-]*(?: [A-Z][\w&.-]*){0,3})", hint) + extract_skills(hint)
    answer = collect(question=hint, before=around.before, after=around.after, company=around.company, role=around.role, round_name=around.round_name, kind=around.kind)
    ctx = DictationContext(dictionary=list(reversed(dictionary)), context_terms=context, starred=mine, hint=hint, answer=answer, prefix=prefix)  # most relevant last
    return ctx, prefs


@router.post("/stt/chunk")
async def transcribe_chunk(
    user: RealUserDep,
    session: SessionDep,
    audio: UploadFile = File(...),
    hint: str = Form(default="", max_length=600),
    before: str = Form(default="", max_length=4000),
    after: str = Form(default="", max_length=2000),
    company: str = Form(default="", max_length=120),
    role: str = Form(default="", max_length=160),
    round_name: str = Form(default="", max_length=80),
    kind: str = Form(default="", max_length=40),
) -> dict:
    """A finished stretch of a long answer, sent while you're still talking (speculative chunking): ASR and the
    hallucination filter only. The clean-up runs once, at release, over the whole answer."""
    if not enabled():
        raise HTTPException(503, "Accurate speech-to-text isn't configured on this server.")
    await hit("stt_chunk", str(user.id))
    data, ext = await _read_audio(audio)
    if not data:
        return {"text": "", "ms": 0}
    from app.dictation.pipeline import transcribe_chunk as run_chunk
    from app.dictation.providers import ASRError

    ctx, _prefs = await _context(session, user, hint, _around(before, after, company, role, round_name, kind))
    try:
        text, ms = await run_chunk(data, f"chunk.{ext}", ctx)
    except ASRError as exc:
        raise HTTPException(502, "Transcription failed.") from exc
    return {"text": text, "ms": ms}


@router.post("/stt")
async def transcribe(
    user: RealUserDep,
    session: SessionDep,
    audio: UploadFile | None = File(default=None),
    hint: str = Form(default="", max_length=600),
    audio_ms: int | None = Form(default=None, ge=0, le=900_000),
    mode: str | None = Form(default=None, pattern="^(polished|verbatim)$"),
    before: str = Form(default="", max_length=4000),
    after: str = Form(default="", max_length=2000),
    company: str = Form(default="", max_length=120),
    role: str = Form(default="", max_length=160),
    round_name: str = Form(default="", max_length=80),
    kind: str = Form(default="", max_length=40),
    prefix: str = Form(default="", max_length=20000),
    chunks: int = Form(default=0, ge=0, le=200),
) -> dict:
    """One dictation through Flowtype's pipeline (see app.dictation): biased ASR with fallback, hallucination filter,
    your dictionary, the clean-up behind its guardrails. `prefix` is the text of the chunks already transcribed while
    you talked; `audio` is the rest. Logs timings (never the audio or text) for latency and Edit Rate."""
    if not enabled():
        raise HTTPException(503, "Accurate speech-to-text isn't configured on this server (it needs GROQ_API_KEY). Live browser recognition still works.")
    await hit("stt", str(user.id))
    data, ext = await _read_audio(audio)
    if not data and not prefix.strip():
        return {"text": "", "model": MODEL}
    from app.dictation.pipeline import run
    from app.dictation.providers import ASRError
    from app.models import Dictation

    ctx, prefs = await _context(session, user, hint, _around(before, after, company, role, round_name, kind), prefix)
    try:
        # Polished (the default) cleans up fillers and self-corrections; word for word keeps exactly what you said.
        mode = mode or prefs.get("speech_mode") or "polished"
        out = await run(data or None, f"answer.{ext}", ctx, user.id, ai_fix=ai_correct, mode=mode)
    except ASRError as exc:
        raise HTTPException(502, "Transcription failed. Your live transcript is kept.") from exc
    out.timings["chunks"] = chunks
    row = Dictation(
        user_id=user.id, model=out.model, fallback=out.fallback, retried=out.retried, audio_ms=audio_ms,
        words=len(out.text.split()), corrections=len(out.corrections), asr_ms=out.timings["asr_ms"], server_ms=out.timings["server_ms"],
        mode=out.mode, guard=out.guard, llm_ms=out.timings["ai_ms"] if out.mode == "polished" and out.guard not in ("", "skipped") else None,
    )
    session.add(row)
    await session.commit()
    return {
        "text": out.text, "model": out.model, "corrections": out.corrections, "dictation_id": str(row.id), "timings": out.timings,
        "fallback": out.fallback, "mode": out.mode, "cleaned": out.guard == "ok", "raw": out.raw if out.mode == "polished" else None,
        "continued": bool(ctx.answer and ctx.answer.continues_sentence and not out.text.startswith("\n")),
    }


class Fixed(BaseModel):
    text: str = Field(description="The transcript with only misheard names and technical terms corrected")


async def ai_correct(text: str, vocab: list[str], hint: str, user_id) -> tuple[str, list[dict]]:
    """A last pass for terms the sound match missed. Every change must be a word from the student's vocabulary,
    otherwise the pass is discarded: it can't rephrase what they said."""
    from app.llm import CallContext, LLMOutputError, LLMUnavailable, get_llm
    from app.services.speech_vocab import guard_ai_fix

    if len(text.split()) < 4 or not vocab:
        return text, []
    try:
        res = await get_llm().structured(
            agent="interviewer",
            tier="fast",
            schema=Fixed,
            ctx=CallContext(user_id=user_id),
            max_tokens=min(2000, 60 + len(text) // 2),
            system=(
                "You correct speech-to-text transcripts. Replace ONLY words that are clearly misheard versions of terms in the "
                "speaker's vocabulary (their name, college, companies, projects, tools). Keep every other word, filler, repetition "
                "and the punctuation exactly as it is. Don't rephrase, don't fix grammar, don't add or remove anything else."
            ),
            prompt=f"Vocabulary: {'; '.join(vocab[:60])}\nQuestion being answered: {hint[:300]}\nTranscript: {text}",
        )
    except (LLMUnavailable, LLMOutputError):
        return text, []
    fixed = re.sub(r"\s+", " ", res.text).strip()
    if not fixed or fixed == text or not guard_ai_fix(text, fixed, vocab):
        return text, []
    from difflib import SequenceMatcher

    a, b = text.split(), fixed.split()
    changes = [{"heard": " ".join(a[i1:i2]), "fixed": " ".join(b[j1:j2])} for op, i1, i2, j1, j2 in SequenceMatcher(None, a, b).get_opcodes() if op == "replace"]
    return fixed, changes


class WordsIn(BaseModel):
    words: list[str] = Field(max_length=100)


@router.get("/stt/words")
async def get_words(user: UserDep, session: SessionDep) -> dict:
    from sqlalchemy import select

    from app.models import Profile

    p = (await session.execute(select(Profile).where(Profile.user_id == user.id))).scalar_one_or_none()
    prefs = (p.preferences if p else None) or {}
    return {"words": prefs.get("speech_words", []), "learned": prefs.get("speech_learned", []), "mode": prefs.get("speech_mode") or "polished"}


class ModeIn(BaseModel):
    mode: str = Field(pattern="^(polished|verbatim)$")


@router.put("/stt/mode")
async def set_mode(body: ModeIn, user: UserDep, session: SessionDep) -> dict:
    """Polished: fillers and self-corrections cleaned up, punctuation and lists added. Word for word: exactly what
    you said, with only your names and terms spelled right."""
    from sqlalchemy import select

    from app.models import Profile

    p = (await session.execute(select(Profile).where(Profile.user_id == user.id))).scalar_one()
    p.preferences = {**(p.preferences or {}), "speech_mode": body.mode}
    await session.commit()
    return {"mode": body.mode}


@router.put("/stt/words")
async def set_words(body: WordsIn, user: UserDep, session: SessionDep) -> dict:
    """Words speech-to-text should always spell your way: your name, college, a project, a tool."""
    from sqlalchemy import select

    from app.models import Profile

    words = list(dict.fromkeys(w.strip()[:60] for w in body.words if w.strip()))[:100]
    p = (await session.execute(select(Profile).where(Profile.user_id == user.id))).scalar_one()
    p.preferences = {**(p.preferences or {}), "speech_words": words}
    await session.commit()
    return {"words": words}



@router.put("/stt/learned")
async def set_learned(body: WordsIn, user: UserDep, session: SessionDep) -> dict:
    """The spellings learned from your corrections (remove one that was learned wrongly)."""
    from sqlalchemy import select

    from app.models import Profile

    words = list(dict.fromkeys(w.strip()[:60] for w in body.words if w.strip()))[:100]
    p = (await session.execute(select(Profile).where(Profile.user_id == user.id))).scalar_one()
    p.preferences = {**(p.preferences or {}), "speech_learned": words}
    await session.commit()
    return {"learned": words}


class DictationUpdate(BaseModel):
    client_ms: int | None = Field(default=None, ge=0, le=120_000, description="Key release to text in the answer box")
    edited: bool | None = None
    edit_ratio: float | None = Field(default=None, ge=0, le=5)
    # At submit: the dictated take and the submitted answer, compared in memory to learn corrected spellings. Never stored.
    dictated: str | None = Field(default=None, max_length=20000, exclude=True)
    final: str | None = Field(default=None, max_length=40000, exclude=True)


@router.patch("/stt/dictations/{dictation_id}")
async def update_dictation(dictation_id: str, body: DictationUpdate, user: UserDep, session: SessionDep) -> dict:
    """The browser reports the end-to-end latency and, at submit, whether the dictated text was edited (Edit Rate)."""
    import uuid

    from app.models import Dictation

    try:
        row = await session.get(Dictation, uuid.UUID(dictation_id))
    except ValueError:
        row = None
    if row is None or row.user_id != user.id:
        raise HTTPException(404, "No such dictation")
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(row, k, v)
    learned: list[str] = []
    if body.dictated and body.final:
        learned = await _learn(session, user, body.dictated, body.final)
    await session.commit()
    return {"ok": True, "learned": learned}


async def _learn(session, user, dictated: str, final: str) -> list[str]:
    """Flowtype's auto-learn: a word you corrected after dictating ("Kavia" → "Kavya") is spelled your way next time."""
    from sqlalchemy import select

    from app.dictation.learn import learn, merge_learned
    from app.models import Profile

    res = learn(dictated, final)
    if not res or not res.corrections:
        return []
    new = [fixed for _wrote, fixed in res.corrections]
    p = (await session.execute(select(Profile).where(Profile.user_id == user.id))).scalar_one_or_none()
    if p is None:
        return []
    prefs = p.preferences or {}
    p.preferences = {**prefs, "speech_learned": merge_learned(list(prefs.get("speech_learned") or []), new, list(prefs.get("speech_words") or []))}
    return new


@router.get("/stt/metrics")
async def stt_metrics(user: UserDep, session: SessionDep, scope: str = "me") -> dict:
    """Latency p50/p95 per stage and the Dictation Edit Rate, for you (or everyone, for admins)."""
    from app.dictation.store import metrics

    if scope == "all" and user.email.lower() in {e.lower() for e in settings.admin_emails}:
        return await metrics(session, None)
    return await metrics(session, user.id)

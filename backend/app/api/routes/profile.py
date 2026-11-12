from fastapi import APIRouter, File, HTTPException, UploadFile, status
from sqlalchemy import select

from app.agents.matcher import ensure_profile_embedding
from app.api.deps import SessionDep, UserDep
from app.llm import CallContext
from app.models import Profile
from app.resume_parser import MAX_RESUME_BYTES, UnsupportedResume, extract_text_report, structure_resume
from app.schemas import Preferences, ProfileOut, ProfileUpdate, ResumeData
from app.services.ingest import ensure_user_targets
from app.services.ratelimit import hit

router = APIRouter(prefix="/profile", tags=["profile"])


async def _profile(session, user_id) -> Profile:
    profile = (await session.execute(select(Profile).where(Profile.user_id == user_id))).scalar_one_or_none()
    if profile is None:
        profile = Profile(user_id=user_id, resume={}, preferences=Preferences().model_dump())
        session.add(profile)
        await session.flush()
    return profile


def _out(p: Profile) -> ProfileOut:
    return ProfileOut(
        resume_filename=p.resume_filename,
        resume=ResumeData.model_validate(p.resume or {}),
        preferences=Preferences.model_validate(p.preferences or {}),
        has_resume=bool(p.resume_text),
        updated_at=p.updated_at,
    )


@router.get("", response_model=ProfileOut)
async def get_profile(user: UserDep, session: SessionDep) -> ProfileOut:
    profile = await _profile(session, user.id)
    await session.commit()
    return _out(profile)


@router.put("", response_model=ProfileOut)
async def update_profile(body: ProfileUpdate, user: UserDep, session: SessionDep) -> ProfileOut:
    profile = await _profile(session, user.id)
    if body.preferences is not None:
        profile.preferences = body.preferences.model_dump()
    if body.resume is not None:
        profile.resume = body.resume.model_dump()
        if not profile.resume_text:
            profile.resume_text = body.resume.embedding_text()
    await session.commit()
    await session.refresh(profile)
    if body.resume is not None:
        await ensure_profile_embedding(profile.id, body.resume)
    out = _out(profile)
    if out.has_resume:  # new boards / searches join the shared index right away
        await ensure_user_targets(out.preferences, out.resume.skills)
    return out


@router.post("/resume", response_model=ProfileOut)
async def upload_resume(user: UserDep, session: SessionDep, file: UploadFile = File(...)) -> ProfileOut:
    await hit("resume_upload", str(user.id))  # each upload is an LLM parse
    data = await file.read(MAX_RESUME_BYTES + 1)
    if len(data) > MAX_RESUME_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Resume must be under 5 MB")
    try:
        text, hidden = extract_text_report(file.filename or "resume", data)
    except UnsupportedResume as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    resume = await structure_resume(text, CallContext(user_id=user.id))
    profile = await _profile(session, user.id)
    # Text hidden from people (white or tiny fonts: ATS keyword stuffing) is removed and flagged, never scored.
    profile.preferences = {**(profile.preferences or {}), "resume_hidden_text": {"count": len(hidden), "sample": [h[:60] for h in hidden[:5]]}}
    profile.resume_filename = file.filename
    profile.resume_text = text
    profile.resume = resume.model_dump()
    await session.commit()
    await session.refresh(profile)
    await ensure_profile_embedding(profile.id, resume)
    out = _out(profile)
    await ensure_user_targets(out.preferences, out.resume.skills)
    return out

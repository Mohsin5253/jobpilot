"""Create (or reset) a demo account with the sample resume, for local dev and screenshots.

  uv run python -m scripts.seed_demo
Credentials: DEMO_EMAIL / DEMO_PASSWORD env vars, defaulting to the values below (local only).
"""

import asyncio
import os
from pathlib import Path

from sqlalchemy import delete

from app.agents.matcher import ensure_profile_embedding
from app.db import session_scope
from app.llm import CallContext
from app.models import Profile, User
from app.resume_parser import extract_text, structure_resume
from app.schemas import Preferences
from app.security import hash_password

EMAIL = os.getenv("DEMO_EMAIL", "demo@example.com")
PASSWORD = os.getenv("DEMO_PASSWORD", "jobpilot-demo")
SAMPLE = Path(__file__).resolve().parents[1] / "evals" / "data" / "sample_resume.md"


async def main() -> None:
    async with session_scope() as s:
        await s.execute(delete(User).where(User.email == EMAIL))
        user = User(email=EMAIL, name="Aarav Mehta", password_hash=hash_password(PASSWORD))
        s.add(user)
    # The user must be committed before the LLM call: its cost row references users.id.
    text = extract_text(SAMPLE.name, SAMPLE.read_bytes())
    resume = await structure_resume(text, CallContext(user_id=user.id))
    async with session_scope() as s:
        profile = Profile(user_id=user.id, resume_filename="sample_resume.md", resume_text=text, resume=resume.model_dump(), preferences=Preferences().model_dump())
        s.add(profile)
        await s.flush()
        profile_id = profile.id
    await ensure_profile_embedding(profile_id, resume)
    print(f"Demo user ready: {EMAIL}")


if __name__ == "__main__":
    asyncio.run(main())

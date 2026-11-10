from fastapi import APIRouter

from app.api.deps import SessionDep, UserDep
from app.services.outcomes import insights

router = APIRouter(prefix="/insights", tags=["insights"])

REJECTION_REASONS = [
    "Skills didn't match",
    "Not enough experience",
    "Eligibility (CGPA, year, branch)",
    "Failed online test",
    "Interview didn't go well",
    "Role filled / closed",
    "Location or work mode",
    "No reason given",
]


@router.get("")
async def my_insights(user: UserDep, session: SessionDep) -> dict:
    return {**await insights(session, [user.id]), "reason_options": REJECTION_REASONS}

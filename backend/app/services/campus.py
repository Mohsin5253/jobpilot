"""Campus placement mode: on-campus drives (eligibility, rounds, dates), internship-to-PPO, and off-campus
applications in one timeline, plus a placement-cell view for colleges."""

from datetime import UTC, datetime

from app.models import CampusDrive

ROUND_PREP: dict[str, list[str]] = {
    "aptitude": ["Quant: percentages, ratios, time & work (30 min a day)", "Logical reasoning: puzzles, seating, syllogisms", "Verbal: reading comprehension, error spotting", "One timed mock test before the drive"],
    "coding": ["Arrays, strings, hashing, two pointers", "Trees, graphs (BFS/DFS), basic DP", "Solve 2 timed problems a day on the platform the company uses", "Revise time and space complexity"],
    "technical": ["Walk through every project on your resume: problem, your part, results", "Core CS: OOP, DBMS (joins, normalisation), OS, networks", "Role basics (e.g. ML: bias/variance, metrics, overfitting)", "Prepare 2 questions to ask the interviewer"],
    "group_discussion": ["Read the news for current topics", "Open with a structure, listen, summarise at the end", "Practise once with friends"],
    "hr": ["Tell me about yourself (60 seconds)", "Why this company, why this role", "Strengths, a weakness you're working on, a conflict you handled", "Relocation, bond and joining-date answers ready"],
}


def eligibility(drive: CampusDrive, academics: dict) -> tuple[bool | None, list[str]]:
    """(eligible?, reasons). None when the student hasn't filled in the academics the drive needs."""
    rules = drive.eligibility or {}
    reasons: list[str] = []
    unknown = False
    if rules.get("min_cgpa") is not None:
        cgpa = academics.get("cgpa")
        if cgpa is None:
            unknown = True
        elif float(cgpa) < float(rules["min_cgpa"]):
            reasons.append(f"CGPA {cgpa} is below the {rules['min_cgpa']} cut-off")
    if rules.get("branches"):
        branch = (academics.get("branch") or "").strip().lower()
        if not branch:
            unknown = True
        elif not any(b.strip().lower() in branch or branch in b.strip().lower() for b in rules["branches"]):
            reasons.append(f"Open to {', '.join(rules['branches'])}")
    if rules.get("max_backlogs") is not None:
        backlogs = academics.get("backlogs")
        if backlogs is None:
            unknown = True
        elif int(backlogs) > int(rules["max_backlogs"]):
            reasons.append(f"At most {rules['max_backlogs']} active backlog(s)")
    if rules.get("grad_years"):
        year = academics.get("grad_year")
        if year is None:
            unknown = True
        elif int(year) not in [int(y) for y in rules["grad_years"]]:
            reasons.append(f"For the {', '.join(str(y) for y in rules['grad_years'])} batch")
    if reasons:
        return False, reasons
    return (None, ["Add your academics in Settings to check eligibility"]) if unknown else (True, [])


def upcoming(drive: CampusDrive, now: datetime | None = None) -> bool:
    now = now or datetime.now(UTC)
    dates = [drive.register_by] + [_dt(r.get("date")) for r in drive.rounds or []]
    return any(d and d >= now for d in dates)


def _dt(value) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        d = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=UTC)
    except ValueError:
        return None


def prep_for(drive: CampusDrive) -> list[dict]:
    return [{"round": r.get("name") or r.get("type", "Round"), "type": r.get("type", "technical"), "checklist": ROUND_PREP.get(r.get("type", ""), [])} for r in drive.rounds or []]

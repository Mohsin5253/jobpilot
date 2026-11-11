"""Keeps interview questions current: measures which skills are rising in each field's postings and refreshes the
question bank around them, weekly.

Measured trends: for every posting fetched in the last 30 days and the 30 days before, the field is detected from
the title and its skills are counted. A skill trends when it appears in a growing share of that field's postings
(at least MIN_POSTINGS mentions). For the top trending skills, new questions are written (by the AI when available,
from templates otherwise) and older ones retire after RETIRE_DAYS.

Baseline: until a field has enough postings to measure, a curated snapshot of what Indian internship and fresher
interviews in that field are asking about now is used, so a brand-new deployment still asks current questions.
The interview shows which kind each question is ("Trending in postings" vs "Current topic").
"""

from collections import Counter
from datetime import UTC, datetime, timedelta

from pydantic import BaseModel, Field
from sqlalchemy import select, text, update

from app.ats_lexicon import INDUSTRIES
from app.db import session_scope
from app.llm import CallContext, LLMOutputError, LLMUnavailable, get_llm
from app.logging import log
from app.models import IndustryTrend, Job, TrendQuestion
from app.services.ats import count_terms, detect_industry
from app.skills import role_digest

WINDOW_DAYS = 30
MIN_POSTINGS = 3
TOP_SKILLS = 6
RETIRE_DAYS = 45
MAX_JOBS = 4000
SNAPSHOT = "Nov 2026"

TECH_FIELDS = {"software", "data_science", "data_analytics", "core_engineering"}

# Curated snapshot: (skill, round kind, question, key points). Reviewed for Indian internship/fresher interviews.
BASELINE: dict[str, list[tuple[str, str, str, tuple[str, ...]]]] = {
    "software": [
        ("LLM integration", "technical", "How would you add an LLM-powered feature (say, summarising support tickets) to an existing backend? Cover the API call, latency, cost and what you'd do when the model is wrong.", ("api", "latency", "cost", "cache", "fallback", "evaluate")),
        ("System design", "technical", "Design a URL shortener for 10 million links. What are the main components, the database choice and how do you handle heavy read traffic?", ("hash", "database", "cache", "read", "scale")),
        ("Cloud-native", "technical", "What changes when you move a monolith into containers on Kubernetes? Mention one benefit and one new problem.", ("container", "deploy", "scale", "service", "config")),
        ("Secure coding", "technical", "What is SQL injection and how do you prevent it in code you write?", ("parameterized", "input", "query", "orm", "validate")),
        ("Testing", "technical", "How do you decide what to unit test versus integration test in a REST API?", ("unit", "integration", "mock", "database", "edge")),
    ],
    "data_science": [
        ("RAG", "technical", "Explain retrieval-augmented generation. How would you chunk documents and evaluate whether answers are grounded?", ("chunk", "embedding", "retrieve", "vector", "evaluate", "hallucination")),
        ("LLM evaluation", "technical", "How do you evaluate an LLM feature before shipping it, beyond eyeballing a few outputs?", ("test set", "metric", "human", "rubric", "regression")),
        ("Fine-tuning vs prompting", "technical", "When would you fine-tune a model instead of improving the prompt or adding retrieval?", ("data", "cost", "domain", "latency", "prompt")),
        ("MLOps", "technical", "Your model's accuracy drops two months after launch. What could cause it and how would you catch it earlier?", ("drift", "monitor", "retrain", "data", "alert")),
        ("Responsible AI", "technical", "How would you check a hiring or loan model for bias against a group of users?", ("fairness", "group", "metric", "data", "audit")),
    ],
    "data_analytics": [
        ("Modern data stack", "technical", "What is dbt used for, and how does it fit between the warehouse and a dashboard?", ("transform", "sql", "model", "warehouse", "test")),
        ("Power BI", "technical", "In Power BI, what's the difference between a calculated column and a measure? When do you use each?", ("row", "context", "aggregate", "dax", "measure")),
        ("AI in analytics", "case", "A manager asks you to use ChatGPT to analyse sales data. What would you let it do, and what would you check yourself?", ("verify", "privacy", "sql", "numbers", "source")),
        ("Product analytics", "case", "How would you measure whether a new 'buy again' button increased repeat orders?", ("a/b", "control", "metric", "baseline", "significance")),
    ],
    "product": [
        ("AI product sense", "case", "Pick a product you use and propose one AI feature for it. Who is it for, what could go wrong, and how do you measure success?", ("user", "problem", "risk", "metric", "launch")),
        ("Metrics", "technical", "What's a good north-star metric for a UPI payments app, and which input metrics drive it?", ("north star", "transactions", "retention", "input", "active")),
        ("Prioritisation", "case", "You have three asks: a bug from a big client, a growth experiment, and tech debt. How do you decide?", ("impact", "effort", "data", "stakeholder", "trade-off")),
    ],
    "design": [
        ("AI-assisted design", "case", "How do you use AI tools in your design process, and where do you not trust them?", ("ideation", "research", "review", "accessibility", "judgement")),
        ("Design systems", "technical", "How would you start a design system for a startup with an inconsistent app?", ("audit", "components", "tokens", "documentation", "adoption")),
        ("Accessibility", "technical", "Name three accessibility checks you run before handing off a screen.", ("contrast", "labels", "keyboard", "focus", "wcag")),
    ],
    "marketing": [
        ("AI content", "case", "How would you use generative AI to scale content for a D2C brand without making it sound generic?", ("brand voice", "edit", "test", "audience", "review")),
        ("Performance marketing", "technical", "Your Meta ads ROAS fell from 3 to 1.8 in a month. How do you diagnose it?", ("creative", "audience", "cpm", "conversion", "attribution")),
        ("Short video", "case", "Plan a 4-week Instagram Reels and YouTube Shorts series for a college-focused app.", ("audience", "hooks", "calendar", "metrics", "creators")),
        ("Marketing analytics", "technical", "What's the difference between CAC and LTV, and why does their ratio matter?", ("acquisition", "lifetime", "ratio", "payback", "retention")),
    ],
    "finance": [
        ("GST e-invoicing", "technical", "What is GST e-invoicing and which businesses must use it?", ("irn", "portal", "turnover", "invoice", "compliance")),
        ("Fintech & UPI", "case", "How does UPI make money for banks and apps when payments are free for users?", ("mdr", "credit", "cross-sell", "data", "lending")),
        ("Financial modelling", "technical", "Walk me through how a ₹1,000 increase in depreciation flows through the three statements.", ("net income", "tax", "cash", "assets", "retained")),
        ("Python in finance", "technical", "Which finance tasks would you automate with Python or Excel macros, and why?", ("reconciliation", "reports", "data", "errors", "time")),
    ],
    "consulting": [
        ("AI strategy", "case", "A mid-size bank wants to 'use GenAI'. How would you structure your first two weeks of work?", ("use cases", "value", "risk", "data", "pilot")),
        ("Digital transformation", "case", "A traditional retailer's online sales are flat. How would you find the cause?", ("customer", "channel", "funnel", "competition", "data")),
    ],
    "sales": [
        ("SaaS sales", "technical", "Explain the stages of a B2B SaaS sales pipeline and the metric you'd watch at each.", ("lead", "qualify", "demo", "close", "conversion")),
        ("Social selling", "case", "How would you use LinkedIn (manually) to open conversations with five target accounts this week?", ("research", "personalise", "value", "follow up", "referral")),
    ],
    "hr": [
        ("AI in hiring", "case", "What are the risks of using AI to screen resumes, and how would you manage them?", ("bias", "transparency", "human review", "audit", "candidates")),
        ("HR analytics", "technical", "Which metrics would you track to reduce early attrition of new joiners?", ("attrition", "90-day", "engagement", "manager", "exit")),
        ("Labour codes", "technical", "What do India's new labour codes change for HR teams, at a high level?", ("wages", "social security", "compliance", "contract", "codes")),
    ],
    "core_engineering": [
        ("EV systems", "technical", "Explain the main parts of an electric vehicle powertrain and the role of the battery management system.", ("battery", "motor", "inverter", "bms", "thermal")),
        ("Industry 4.0 / IoT", "technical", "How would you add sensors and dashboards to monitor a factory machine for failures?", ("sensor", "data", "threshold", "predictive", "maintenance")),
        ("Simulation", "technical", "When do you trust a simulation (FEA/CFD) result, and how do you validate it?", ("mesh", "boundary", "validation", "experiment", "convergence")),
    ],
    "operations": [
        ("Quick commerce", "case", "How does a 10-minute delivery dark store decide what to stock?", ("demand", "sku", "inventory", "data", "space")),
        ("Supply chain analytics", "technical", "What is demand forecasting error (like MAPE) and how would you reduce it?", ("forecast", "error", "seasonality", "data", "review")),
        ("SAP / ERP", "technical", "What does an ERP like SAP do for a purchase-to-pay process?", ("purchase order", "goods receipt", "invoice", "payment", "approval")),
    ],
}


class Generated(BaseModel):
    question: str = Field(description="One interview question, under 45 words")
    key_points: list[str] = Field(description="3-6 short phrases a strong answer mentions", max_length=6)


async def ensure_baseline() -> int:
    """Loads the curated snapshot once (and on new deployments). Idempotent."""
    async with session_scope() as s:
        have = {(q.industry, q.skill) for q in (await s.execute(select(TrendQuestion).where(TrendQuestion.source == "baseline"))).scalars()}
        added = 0
        for ind, rows in BASELINE.items():
            for skill, kind, q, points in rows:
                if (ind, skill) not in have:
                    s.add(TrendQuestion(industry=ind, round_kind=kind, skill=skill, question=q, key_points=list(points), source="baseline"))
                    added += 1
            if await s.get(IndustryTrend, ind) is None:
                s.add(IndustryTrend(industry=ind, skills=[{"skill": sk, "growth": None, "share": None, "postings": 0} for sk, *_ in rows], source="baseline"))
        return added


def measure(jobs_now: list[tuple[str, str, list[str]]], jobs_before: list[tuple[str, str, list[str]]]) -> dict[str, dict]:
    """{industry: {"postings": n, "skills": [{skill, share, previous, growth, postings}]}} from (title, description, skills)."""

    def tally(jobs):
        per: dict[str, Counter] = {}
        totals: Counter = Counter()
        for title, desc, skills in jobs:
            ind, _ = detect_industry(title, desc[:600])
            totals[ind] += 1
            found = set(skills or []) | set(count_terms(f"{title}\n{role_digest(desc or '', 3000)}", ind))
            per.setdefault(ind, Counter()).update(found)
        return per, totals

    now, n_now = tally(jobs_now)
    before, n_before = tally(jobs_before)
    out = {}
    for ind, counts in now.items():
        if ind not in INDUSTRIES:
            continue
        rows = []
        for skill, c in counts.items():
            if c < MIN_POSTINGS or skill in ("Communication", "Teamwork"):
                continue
            share = c / n_now[ind]
            prev = (before.get(ind, Counter())[skill] / n_before[ind]) if n_before[ind] >= MIN_POSTINGS * 3 else None
            # No earlier window to compare with (a new deployment): demand is measured, growth is unknown.
            growth = None if prev is None else round((share - prev) / prev, 2) if prev else 1.0
            rows.append({"skill": skill, "share": round(share, 3), "previous": None if prev is None else round(prev, 3), "growth": growth, "postings": c})
        rows.sort(key=lambda r: r["share"] * (1 + max(-0.9, r["growth"] or 0)), reverse=True)
        out[ind] = {"postings": n_now[ind], "skills": rows[:12]}
    return out


def template_question(industry: str, skill: str) -> Generated:
    if industry in TECH_FIELDS:
        return Generated(question=f"{skill} is showing up in more {INDUSTRIES[industry].name.lower()} postings. Tell me what it is used for and one way you have used it, or would use it, in a project.", key_points=[skill.lower(), "project", "why", "result"])
    return Generated(question=f"More {INDUSTRIES[industry].name.lower()} roles now ask for {skill}. How would you apply it in your first month here? Give one concrete example.", key_points=[skill.lower(), "example", "measure", "result"])


async def refresh(now: datetime | None = None) -> dict:
    """Weekly: measure trends from postings and write questions for the top rising skills. Advisory-locked."""
    now = now or datetime.now(UTC)
    await ensure_baseline()
    async with session_scope() as s:
        if not (await s.execute(text("SELECT pg_try_advisory_xact_lock(724020)"))).scalar():
            return {"skipped": "locked"}
        cut, prev_cut = now - timedelta(days=WINDOW_DAYS), now - timedelta(days=2 * WINDOW_DAYS)
        rows_now = (await s.execute(select(Job.title, Job.description, Job.skills).where(Job.fetched_at >= cut).limit(MAX_JOBS))).all()
        rows_before = (await s.execute(select(Job.title, Job.description, Job.skills).where(Job.fetched_at >= prev_cut, Job.fetched_at < cut).limit(MAX_JOBS))).all()
    measured = measure([tuple(r) for r in rows_now], [tuple(r) for r in rows_before])
    written = 0
    llm = get_llm()
    for ind, data in measured.items():
        if data["postings"] < 20:  # too few postings to call anything a trend: keep the curated snapshot
            continue
        async with session_scope() as s:
            row = await s.get(IndustryTrend, ind)
            if row is None:
                row = IndustryTrend(industry=ind)
                s.add(row)
            row.skills, row.postings, row.source, row.refreshed_at = data["skills"], data["postings"], "postings", now
            have = {q.skill.lower() for q in (await s.execute(select(TrendQuestion).where(TrendQuestion.industry == ind, TrendQuestion.active, TrendQuestion.source != "baseline"))).scalars()}
        for t in data["skills"][:TOP_SKILLS]:
            if t["skill"].lower() in have:
                continue
            try:
                gen = await llm.structured(
                    agent="interviewer",
                    tier="fast",
                    schema=Generated,
                    ctx=CallContext(),
                    max_tokens=400,
                    system="You write one realistic interview question for an Indian internship or fresher role. It must test real understanding of the skill, not trivia. Plain English.",
                    prompt=f"Field: {INDUSTRIES[ind].name}\nSkill rising in job postings: {t['skill']} (in {round(100 * t['share'])}% of recent postings)\nRound: {'technical' if ind in TECH_FIELDS else 'case'}",
                )
                source = "ai"
            except (LLMUnavailable, LLMOutputError):
                gen, source = template_question(ind, t["skill"]), "postings"
            async with session_scope() as s:
                s.add(TrendQuestion(industry=ind, round_kind="technical" if ind in TECH_FIELDS else "case", skill=t["skill"], question=gen.question.strip(), key_points=[k.lower() for k in gen.key_points][:6], source=source, growth=t["growth"]))
            written += 1
    async with session_scope() as s:
        await s.execute(update(TrendQuestion).where(TrendQuestion.source != "baseline", TrendQuestion.created_at < now - timedelta(days=RETIRE_DAYS)).values(active=False))
    log.info("trends.refreshed", industries=len(measured), questions=written)
    return {"industries": {k: v["postings"] for k, v in measured.items()}, "questions": written}


async def trend_questions(industry: str, limit: int = 4, seed: int = 0) -> list[dict]:
    """Active questions for a field, measured-trend ones first, rotating with the seed so retakes differ."""
    await ensure_baseline()
    async with session_scope() as s:
        qs = (await s.execute(select(TrendQuestion).where(TrendQuestion.industry == industry, TrendQuestion.active))).scalars().all()
    measured = [q for q in qs if q.source != "baseline"]
    base = [q for q in qs if q.source == "baseline"]
    ordered = sorted(measured, key=lambda q: -(q.growth or 0))
    if base:
        k = seed % len(base)
        ordered += base[k:] + base[:k]
    return [
        {"id": str(q.id), "skill": q.skill, "q": q.question, "key_points": q.key_points, "round_kind": q.round_kind, "label": (f"Rising in postings: {q.skill} (+{round(100 * q.growth)}%)" if q.growth and q.growth > 0 else f"In demand in recent postings: {q.skill}") if q.source != "baseline" else f"Current topic ({SNAPSHOT}): {q.skill}"}
        for q in ordered[:limit]
    ]


async def trending_skills(industry: str) -> dict:
    await ensure_baseline()
    async with session_scope() as s:
        row = await s.get(IndustryTrend, industry)
    if row is None:
        return {"industry": industry, "skills": [], "source": "none", "refreshed_at": None, "postings": 0}
    return {"industry": industry, "skills": row.skills, "source": row.source, "refreshed_at": row.refreshed_at.isoformat() if row.refreshed_at else None, "postings": row.postings}


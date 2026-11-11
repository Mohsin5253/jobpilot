"""Mock interview rounds, per industry, the way Indian internship and fresher interviews actually run.

Each field has its own sequence of rounds (a screening call, then the field's technical or case round, a project or
portfolio deep-dive, and an HR/behavioural round). Questions come from three places, in this order of priority:
the job description's own requirement lines (so feedback can quote the line each question tests), the student's own
projects and proof, and a curated bank per round. Bank questions carry the key points a good answer covers, so the
rule-based grader can score relevance without an LLM; the AI grader (when available) uses the same rubric.
"""

from dataclasses import dataclass, field

from app.ats_lexicon import INDUSTRIES
from app.services.ats import detect_industry
from app.skills import extract_skills


@dataclass(frozen=True)
class BankQ:
    q: str
    tests: str
    key_points: tuple[str, ...] = ()
    seconds: int = 150


@dataclass(frozen=True)
class Round:
    name: str
    kind: str  # screening | technical | case | project | behavioural | roleplay | portfolio
    intro: str
    bank: tuple[BankQ, ...] = field(default_factory=tuple)
    take: int = 2  # bank questions asked in this round (JD questions are added to technical rounds)


SCREENING = Round(
    "Screening call",
    "screening",
    "Let's start with a short screening conversation.",
    (
        BankQ("Tell me about yourself, in about a minute.", "Clear, relevant self-introduction", ("studying", "project", "skills", "interested", "internship"), 90),
        BankQ("Why do you want this internship, and why our company?", "Motivation and research about the company", ("company", "role", "learn", "product", "because"), 90),
    ),
)
HR = Round(
    "HR & behavioural",
    "behavioural",
    "Last round: a few HR and behavioural questions.",
    (
        BankQ("Tell me about a time a team project went wrong. What did you do?", "Ownership and teamwork (STAR)", ("team", "problem", "i ", "result", "learned"), 150),
        BankQ("What's your biggest weakness, and what are you doing about it?", "Self-awareness", ("weakness", "improve", "working on", "example"), 90),
        BankQ("Where do you see yourself in two years?", "Direction and fit", ("learn", "role", "grow", "skills"), 90),
        BankQ("Tell me about a time you had to learn something quickly.", "Learning agility", ("learned", "days", "week", "built", "result"), 120),
    ),
    take=2,
)

ROUNDS: dict[str, tuple[Round, ...]] = {
    "software": (
        SCREENING,
        Round(
            "Technical: CS fundamentals & DSA",
            "technical",
            "Now the technical round. Talk me through your thinking, not just the answer.",
            (
                BankQ("How would you find whether an array has a duplicate? Give two approaches and their time and space complexity.", "Data structures, complexity analysis", ("hash", "set", "sort", "o(n)", "o(n log n)", "space")),
                BankQ("What is the difference between a process and a thread?", "Operating systems", ("memory", "shared", "process", "thread", "context switch")),
                BankQ("Explain the difference between an INNER JOIN and a LEFT JOIN with an example.", "DBMS / SQL", ("inner", "left", "null", "matching", "rows")),
                BankQ("What happens when you type a URL into the browser and press enter?", "Networking and the web", ("dns", "tcp", "http", "server", "response", "render")),
                BankQ("How does a hash map work internally, and what is a collision?", "Data structures", ("hash function", "bucket", "collision", "chaining", "load factor")),
                BankQ("What is the difference between REST and GraphQL? When would you pick each?", "API design", ("endpoint", "query", "over-fetching", "schema", "http")),
            ),
            take=3,
        ),
        Round(
            "Project deep-dive",
            "project",
            "Let's go deeper into something you built.",
            (BankQ("Pick your strongest project. What was the hardest bug you hit, and how did you find it?", "Debugging and ownership", ("bug", "logs", "found", "fixed", "test"), 150),),
            take=1,
        ),
        HR,
    ),
    "data_science": (
        SCREENING,
        Round(
            "Statistics & ML fundamentals",
            "technical",
            "Technical round: statistics and machine learning.",
            (
                BankQ("Explain the bias-variance trade-off. How do you tell which one your model suffers from?", "ML fundamentals", ("bias", "variance", "underfit", "overfit", "train", "validation")),
                BankQ("When would you prefer precision over recall? Give a real example.", "Model evaluation", ("precision", "recall", "false positive", "false negative", "threshold")),
                BankQ("How do you handle a heavily imbalanced dataset?", "Practical ML", ("resample", "smote", "class weight", "f1", "auc", "stratified")),
                BankQ("What is a p-value, in plain words?", "Statistics", ("null hypothesis", "probability", "extreme", "significance")),
                BankQ("How would you prevent data leakage in a model pipeline?", "ML rigour", ("split", "before", "fit", "train only", "pipeline", "future")),
            ),
            take=3,
        ),
        Round(
            "Project deep-dive",
            "project",
            "Let's talk about a model you built end to end.",
            (BankQ("Walk me through one model you built: the data, the baseline, the metric you chose and why, and what you'd improve.", "End-to-end ML thinking", ("data", "baseline", "metric", "because", "improve"), 180),),
            take=1,
        ),
        HR,
    ),
    "data_analytics": (
        SCREENING,
        Round(
            "SQL & Excel",
            "technical",
            "Technical round: SQL and spreadsheets.",
            (
                BankQ("How would you find the second-highest salary in an employees table? Describe the query.", "SQL", ("order by", "limit", "offset", "max", "dense_rank", "subquery")),
                BankQ("What is a window function? Give one example where you'd use it.", "SQL", ("over", "partition by", "rank", "running total", "row_number")),
                BankQ("VLOOKUP vs INDEX-MATCH (or XLOOKUP): what's the difference and which do you use?", "Excel", ("left", "column", "exact match", "flexible", "lookup")),
                BankQ("How do you clean a dataset before analysis?", "Data cleaning", ("missing", "duplicates", "outliers", "types", "validate")),
            ),
            take=2,
        ),
        Round(
            "Business case",
            "case",
            "Now a short business case. Structure your answer.",
            (
                BankQ("Weekly orders dropped 20% last week. How would you find out why?", "Root-cause analysis", ("segment", "region", "funnel", "data", "hypothesis", "external")),
                BankQ("Which 3 KPIs would you put on a dashboard for a food-delivery city manager, and why?", "Metrics thinking", ("orders", "delivery time", "cancellation", "retention", "because")),
            ),
            take=1,
        ),
        HR,
    ),
    "product": (
        SCREENING,
        Round(
            "Product sense",
            "case",
            "Product sense round. Think about users first.",
            (
                BankQ("Pick an app you use daily. What's one thing you'd improve, for whom, and how would you know it worked?", "Product sense", ("user", "problem", "solution", "metric", "prioritise")),
                BankQ("Design a feature that helps first-time UPI users in small towns feel safe paying.", "User empathy and design", ("user", "trust", "fraud", "simple", "language", "metric")),
            ),
            take=1,
        ),
        Round(
            "Analytical & metrics",
            "technical",
            "Analytical round.",
            (
                BankQ("Daily active users fell 10% overnight. Walk me through how you'd investigate.", "Metric diagnosis", ("internal", "external", "segment", "platform", "release", "data")),
                BankQ("What would be the north-star metric for a quick-commerce app, and what are its input metrics?", "Metrics frameworks", ("north star", "orders", "retention", "delivery", "input")),
                BankQ("How would you prioritise five feature requests with one sprint of engineering time?", "Prioritisation", ("impact", "effort", "rice", "users", "data")),
            ),
            take=2,
        ),
        HR,
    ),
    "design": (
        SCREENING,
        Round(
            "Portfolio walkthrough",
            "portfolio",
            "Walk me through your portfolio.",
            (
                BankQ("Take one case study from your portfolio: the problem, your research, two options you rejected, and the final design.", "Design process", ("problem", "research", "users", "iteration", "rejected", "final"), 180),
                BankQ("Tell me about a design decision that user testing changed.", "Evidence-led design", ("tested", "users", "changed", "because", "result")),
            ),
            take=2,
        ),
        Round(
            "Design challenge",
            "case",
            "A quick design challenge. Describe your approach out loud.",
            (
                BankQ("Design the onboarding for a budgeting app for college students. Who are the users and what are the first three screens?", "Product design thinking", ("users", "goal", "screens", "flow", "simple", "test")),
                BankQ("How would you make a checkout form accessible?", "Accessibility", ("contrast", "labels", "keyboard", "screen reader", "errors", "wcag")),
            ),
            take=1,
        ),
        HR,
    ),
    "marketing": (
        SCREENING,
        Round(
            "Marketing fundamentals",
            "technical",
            "Marketing fundamentals.",
            (
                BankQ("Explain CTR, CPC and ROAS, and how they relate.", "Performance metrics", ("click", "cost", "revenue", "spend", "impressions")),
                BankQ("How does a page rank on Google? Name three things you'd do for SEO.", "SEO", ("keywords", "content", "backlinks", "speed", "meta")),
                BankQ("Which social platform would you pick to reach college students in tier-2 cities, and why?", "Channel strategy", ("audience", "instagram", "youtube", "content", "cost")),
            ),
            take=2,
        ),
        Round(
            "Campaign case",
            "case",
            "A campaign case.",
            (BankQ("You have ₹50,000 to launch a new snack brand in Pune. Plan the first month.", "Campaign planning", ("audience", "channels", "budget", "content", "measure", "kpi"), 180),),
            take=1,
        ),
        HR,
    ),
    "finance": (
        SCREENING,
        Round(
            "Finance technical",
            "technical",
            "Finance technical round.",
            (
                BankQ("How are the three financial statements linked?", "Accounting", ("net income", "retained earnings", "cash flow", "balance sheet", "depreciation")),
                BankQ("Walk me through a DCF valuation.", "Valuation", ("free cash flow", "discount", "wacc", "terminal value", "present value")),
                BankQ("What is working capital, and why does it matter to a business?", "Corporate finance", ("current assets", "current liabilities", "liquidity", "cash")),
                BankQ("How does input tax credit work under GST?", "Indian taxation", ("input", "output", "credit", "set off", "invoice")),
            ),
            take=2,
        ),
        Round(
            "Markets & case",
            "case",
            "Now something about markets.",
            (BankQ("Pitch me one listed Indian company you'd invest in, with two reasons and one risk.", "Investment thinking", ("revenue", "growth", "valuation", "risk", "because"), 150),),
            take=1,
        ),
        HR,
    ),
    "consulting": (
        SCREENING,
        Round(
            "Guesstimate",
            "case",
            "Let's do a guesstimate. Structure first, then numbers.",
            (BankQ("Estimate the number of cars sold in Bengaluru in a year.", "Structured estimation", ("population", "households", "assume", "replacement", "segment"), 180),),
            take=1,
        ),
        Round(
            "Case interview",
            "case",
            "A business case.",
            (
                BankQ("A chain of 40 chai cafés has seen profits fall 15% in a year. How would you find the cause?", "Profitability framework", ("revenue", "cost", "price", "volume", "fixed", "variable")),
                BankQ("Should a mid-size Indian edtech enter the Middle East? How would you decide?", "Market entry", ("market size", "competition", "capabilities", "risk", "economics")),
            ),
            take=1,
        ),
        HR,
    ),
    "sales": (
        SCREENING,
        Round(
            "Sales role-play",
            "roleplay",
            "Role-play: I'm a busy shop owner. Sell to me.",
            (
                BankQ("Pitch me a billing app for my kirana store in 60 seconds.", "Pitching", ("problem", "save", "time", "benefit", "price", "trial"), 90),
                BankQ("I say: 'It's too expensive, I'll think about it.' How do you respond?", "Objection handling", ("understand", "value", "roi", "question", "next step")),
            ),
            take=2,
        ),
        Round(
            "Sales fundamentals",
            "technical",
            "A couple of sales fundamentals.",
            (
                BankQ("How do you build a pipeline of leads for a B2B product from scratch?", "Prospecting", ("icp", "linkedin", "referrals", "crm", "qualify")),
                BankQ("Tell me about a time you convinced someone to change their mind.", "Persuasion (STAR)", ("situation", "listened", "showed", "result")),
            ),
            take=1,
        ),
        HR,
    ),
    "hr": (
        SCREENING,
        Round(
            "HR fundamentals",
            "technical",
            "HR fundamentals.",
            (
                BankQ("What sourcing channels would you use to hire 20 interns in a month?", "Talent acquisition", ("campus", "referrals", "job portals", "linkedin", "screening")),
                BankQ("Design a first-week onboarding plan for new interns.", "Onboarding", ("buddy", "documents", "training", "goals", "feedback")),
                BankQ("What is the POSH Act, and what must a company have under it?", "Compliance", ("internal committee", "complaint", "policy", "awareness")),
            ),
            take=2,
        ),
        Round(
            "Situational",
            "case",
            "A situation.",
            (BankQ("A candidate accepts an offer and then stops responding a week before joining. What do you do?", "Candidate management", ("call", "reason", "backup", "pipeline", "document")),),
            take=1,
        ),
        HR,
    ),
    "core_engineering": (
        SCREENING,
        Round(
            "Core technical",
            "technical",
            "Technical round on your core subjects.",
            (
                BankQ("Explain stress, strain and the elastic limit with a real example.", "Strength of materials", ("stress", "strain", "elastic", "young's modulus", "deform")),
                BankQ("What are the first and second laws of thermodynamics, in practical terms?", "Thermodynamics", ("energy", "conserved", "entropy", "heat", "efficiency")),
                BankQ("How does a PLC control a machine? Describe a simple ladder logic example.", "Automation", ("input", "output", "scan", "ladder", "sensor")),
                BankQ("What is the difference between a microcontroller and a microprocessor?", "Electronics", ("memory", "peripherals", "embedded", "cpu", "on-chip")),
                BankQ("How do you ensure quality in a production line? Mention any tools you know.", "Quality", ("inspection", "six sigma", "spc", "root cause", "5 why")),
            ),
            take=3,
        ),
        Round(
            "Project deep-dive",
            "project",
            "Tell me about your final-year or best project.",
            (BankQ("Walk me through your best engineering project: the design, the calculations or simulations, and what you'd change.", "Engineering depth", ("design", "calculated", "simulation", "tested", "improve"), 180),),
            take=1,
        ),
        HR,
    ),
    "operations": (
        SCREENING,
        Round(
            "Operations fundamentals",
            "technical",
            "Operations fundamentals.",
            (
                BankQ("What is inventory turnover, and how would you improve it?", "Inventory", ("cost of goods", "average inventory", "demand", "stock", "reorder")),
                BankQ("What is EOQ and when is it useful?", "Planning", ("ordering cost", "holding cost", "demand", "quantity")),
                BankQ("What does an SLA mean for a delivery operation, and how do you track it?", "Service levels", ("time", "target", "breach", "dashboard", "root cause")),
            ),
            take=2,
        ),
        Round(
            "Operations case",
            "case",
            "An operations case.",
            (BankQ("Deliveries in one city are 30% late this month. How do you fix it?", "Process problem solving", ("data", "root cause", "capacity", "routes", "staffing", "measure"), 180),),
            take=1,
        ),
        HR,
    ),
}


def _jd_questions(jd_lines: list[str], take: int) -> list[dict]:
    out, seen = [], set()
    for line in jd_lines:
        skills = [s for s in extract_skills(line) if s not in seen]
        if skills:
            seen.add(skills[0])
            out.append({"kind": "skill", "skill": skills[0], "jd_line": line, "q": f"The role needs {skills[0]}. Tell me about a time you used it: what you built, what was hard, and the result.", "key_points": [skills[0].lower()], "seconds": 150})
        if len(out) >= take:
            break
    if len(out) < take:
        for line in jd_lines:
            if not extract_skills(line) and len(out) < take:
                out.append({"kind": "situational", "skill": None, "jd_line": line, "q": f"The role asks for this: “{line[:140]}”. How have you shown it, or how would you approach it in your first month?", "key_points": [], "seconds": 150})
    return out


DURATIONS = (30, 45, 60)
# Real interviews spend longer on a case or role-play than on a factual question: minimum answer time per round kind.
MIN_SECONDS = {"case": 360, "roleplay": 240, "portfolio": 300, "project": 240}
OVERHEAD_S = 60  # reading the question, the interviewer's follow-up and feedback

# Deeper questions and follow-ups for each field's core rounds, so 45 and 60-minute interviews go deeper, not wider.
EXTRA: dict[str, dict[str, tuple[BankQ, ...]]] = {
    "marketing": {
        "case": (
            BankQ("Follow-up: halfway through the month your CAC is double the target. What do you cut, what do you keep, and why?", "Budget trade-offs under pressure", ("cac", "cut", "channels", "data", "test"), 300),
            BankQ("How would you measure whether an influencer campaign actually drove sales, not just views?", "Attribution", ("utm", "codes", "attribution", "control", "conversion"), 300),
        ),
        "technical": (
            BankQ("Walk me through how you'd set up a Google Ads search campaign for a coaching institute: structure, keywords and bidding.", "Paid search", ("campaign", "ad groups", "keywords", "negative", "bidding", "landing page"), 240),
            BankQ("What does a good marketing funnel report look like for an app? Name the stages and one metric for each.", "Funnel metrics", ("awareness", "install", "activation", "retention", "conversion"), 180),
        ),
    },
    "finance": {
        "case": (
            BankQ("Follow-up: what single number would change your mind about that company, and where would you find it?", "Investment judgement", ("metric", "annual report", "valuation", "risk"), 240),
            BankQ("A client's working capital cycle went from 60 to 95 days. What could be happening and what would you look at first?", "Working-capital diagnosis", ("receivables", "inventory", "payables", "cash", "days"), 300),
        ),
    },
    "consulting": {
        "case": (
            BankQ("Follow-up: your client can only fund one fix this year. Which do you recommend, and how do you size its impact?", "Prioritisation and sizing", ("impact", "cost", "assume", "estimate", "recommend"), 360),
            BankQ("Estimate the yearly revenue of a single Bengaluru metro station's food stalls.", "Guesstimate", ("footfall", "conversion", "ticket size", "assume", "days"), 420),
        ),
    },
    "sales": {
        "roleplay": (
            BankQ("Role-play continued: the owner says 'my nephew already does this for free'. Respond.", "Competitive objection", ("understand", "value", "time", "risk", "trial"), 180),
            BankQ("Close the call: ask for the next step in a way that's hard to say no to.", "Closing", ("next step", "date", "trial", "decision maker"), 150),
        ),
        "technical": (BankQ("How do you qualify a lead? Explain BANT or another framework with an example.", "Qualification", ("budget", "authority", "need", "timeline"), 180),),
    },
    "hr": {
        "case": (
            BankQ("Two managers both want the only strong intern candidate. How do you decide and communicate it?", "Stakeholder management", ("criteria", "fit", "communicate", "fair", "data"), 300),
            BankQ("Exit interviews show interns leave because of unclear work. Propose a fix and how you'd measure it.", "Retention", ("onboarding", "goals", "manager", "survey", "metric"), 300),
        ),
    },
    "operations": {
        "case": (
            BankQ("Follow-up: your fix needs 3 extra riders per shift. How do you justify the cost?", "Business case", ("cost", "late", "refunds", "retention", "compare"), 300),
            BankQ("A warehouse's picking errors doubled after a layout change. How do you investigate?", "Process root cause", ("data", "observe", "sku", "layout", "training"), 300),
        ),
    },
    "product": {
        "case": (
            BankQ("Follow-up: engineering says your feature takes 3 months. What's the smallest version you'd ship in 3 weeks to learn?", "MVP scoping", ("mvp", "learn", "metric", "scope", "users"), 300),
            BankQ("Write the success metric and one guardrail metric for a new 'pay later' button in a food app.", "Metrics design", ("success", "guardrail", "default", "orders", "repayment"), 240),
        ),
    },
    "design": {
        "case": (
            BankQ("Follow-up: usability testing shows users miss your main button. What do you change and how do you retest?", "Iteration", ("hierarchy", "contrast", "test", "users", "measure"), 300),
            BankQ("Critique the checkout of an app you use: one thing that works, one that doesn't, and your fix.", "Design critique", ("users", "friction", "fix", "why"), 240),
        ),
    },
}


def level_of(title: str) -> str:
    """intern for internships and summer roles; fresher for entry-level full-time (SDE-1, GET, analyst, trainee)."""
    t = title.lower()
    return "intern" if any(w in t for w in ("intern", "internship", "summer", "apprentice", "co-op")) else "fresher"


# What a good candidate shows in each kind of round, per field: the bar the report measures against.
NORMS_DEFAULT = {
    "screening": "Clear 60-second introduction that links your studies and projects to this role, and a reason for this company that shows you researched it.",
    "technical": "Correct fundamentals explained in your own words, with an example from your own work; you say what you don't know instead of guessing.",
    "coding": "A working solution within the time, edge cases handled, complexity stated, readable code with good names.",
    "project": "You can explain the problem, your own contribution, design choices with trade-offs, and a measurable result.",
    "portfolio": "A case study told as problem → research → options → decision → outcome, with evidence from users.",
    "case": "A structured approach (framework first), reasonable assumptions stated aloud, numbers where possible, and a clear recommendation.",
    "roleplay": "You listen first, tie the product to the customer's problem, handle the objection calmly and ask for a next step.",
    "behavioural": "STAR answers (situation, task, action, result) with your own actions and what you learned.",
}
NORMS: dict[str, dict[str, str]] = {
    "software": {
        "coding": "Indian product-company bar: solve an easy problem fully and a medium one with the optimal approach in about 20-25 minutes, state time and space complexity, and test edge cases.",
        "technical": "Core CS (DSA, OS, DBMS, networks) explained with examples; for backend roles, APIs, databases and basic system design.",
    },
    "data_science": {
        "coding": "Write correct Python for metrics, vectors and data handling without libraries, handle edge cases (zero division, empty input), and explain complexity.",
        "technical": "ML fundamentals (bias-variance, metrics, leakage), plus current GenAI practice: RAG, embeddings and evaluating LLM output.",
    },
    "data_analytics": {
        "coding": "Translate SQL thinking (GROUP BY, window functions, dedupe) into correct code, and handle empty and duplicate data.",
        "technical": "SQL and Excel/Power BI fluency, and turning data into a recommendation a business team can act on.",
    },
    "core_engineering": {"coding": "Correct bit-level and embedded-style logic with attention to overflow and data sizes.", "technical": "Core subject fundamentals with units and real examples from labs or projects."},
    "product": {"case": "User-first framing, a clear prioritisation and the metric that would prove success."},
    "design": {"portfolio": "Evidence-led design: research, iteration and the outcome, plus accessibility."},
    "marketing": {"case": "A plan tied to an audience and budget with measurable KPIs (CTR, CAC, ROAS) and how you'd test and learn."},
    "finance": {"technical": "Accounting links, valuation steps and Indian taxation basics (GST, TDS) stated precisely."},
    "consulting": {"case": "MECE structure, explicit assumptions, quick maths and a so-what recommendation."},
    "sales": {"roleplay": "Discovery questions before pitching, value tied to the customer, objection handled, next step asked for."},
    "hr": {"technical": "Practical HR processes and Indian compliance (POSH, PF/ESI, labour codes) explained correctly."},
    "operations": {"case": "Data-first root-cause analysis and a fix with a KPI to track it."},
}
BAR = {"intern": 3.2, "fresher": 3.6}  # average rubric score (1-5) a round needs to meet the bar at this level


def norm_for(industry: str, kind: str) -> str:
    return NORMS.get(industry, {}).get(kind) or NORMS_DEFAULT.get(kind, NORMS_DEFAULT["technical"])


def build_plan(
    industry_key: str | None,
    title: str,
    company: str,
    jd_lines: list[str],
    evidence: dict | None,
    resume_projects: list[str],
    minutes: int = 45,
    level: str | None = None,
    trend_qs: list[dict] | None = None,
    trending: list[str] | None = None,
    seed: int = 0,
) -> tuple[list[dict], list[dict], str, str]:
    """(rounds, questions, industry, level) for a real-length interview (30, 45 or 60 minutes)."""
    from app.services.coding_bank import CODING_INDUSTRIES, pick_problems

    minutes = minutes if minutes in DURATIONS else 45
    level = level or level_of(title)
    key = industry_key if industry_key in ROUNDS else detect_industry(title, "\n".join(jd_lines))[0]
    rounds_def = list(ROUNDS.get(key) or ROUNDS["software"])
    coding = key in CODING_INDUSTRIES
    if coding:
        at = next((i + 1 for i, r in enumerate(rounds_def) if r.kind == "technical"), 1)
        rounds_def.insert(at, Round("Coding round", "coding", "Coding round. Think out loud, explain your approach, then code it. You can run the sample tests before you submit."))

    # Candidate questions per round, best first.
    jd_qs = _jd_questions(jd_lines, 3)
    trends = list(trend_qs or [])
    repos = [r.get("name") for r in ((evidence or {}).get("github") or {}).get("top_repos", [])[:2] if r.get("name")]
    candidates: list[list[dict]] = []
    for rd in rounds_def:
        qs: list[dict] = []
        if rd.kind == "screening":
            qs.append({"kind": "screening", "skill": None, "jd_line": f"{title} at {company}", "q": rd.bank[0].q, "key_points": list(rd.bank[0].key_points), "seconds": rd.bank[0].seconds})
            qs.append({"kind": "screening", "skill": None, "jd_line": f"Why {company}", "q": f"Why do you want this {title} role, and why {company}?", "key_points": [company.lower().split()[0] if company else "company", "role", "learn"], "seconds": 90})
        elif rd.kind == "coding":
            for p in pick_problems(key, level, minutes, trending, seed):
                qs.append({"kind": "coding", "skill": None, "jd_line": f"Coding: {', '.join(p.tags)} ({p.difficulty})", "q": f"{p.title}: {p.statement}", "key_points": [], "seconds": p.minutes * 60, "problem": p.public()})
        else:
            if rd.kind == "technical" and jd_qs:
                qs += jd_qs[:2]
                jd_qs = jd_qs[2:]
            # Trend questions go to the field's main round: technical for tech fields, the case/role-play round otherwise.
            if trends and (rd.kind == "technical" or (not coding and rd.kind in ("case", "roleplay", "portfolio"))):
                for t in trends[:2]:
                    qs.append({"kind": rd.kind, "skill": t["skill"], "jd_line": t["label"], "q": t["q"], "key_points": t["key_points"], "seconds": 150, "trend": True})
                trends = trends[2:]
            if rd.kind in ("project", "portfolio"):
                for name in (repos or resume_projects)[:1]:
                    qs.append({"kind": "proof", "skill": None, "jd_line": f"Your project: {name}", "q": f"Walk me through {name}: the problem, your design choices, and one thing you'd do differently.", "key_points": ["problem", "chose", "because", "differently"], "seconds": 180})
            bank = list(rd.bank)
            n = len(bank)
            ordered = [bank[(seed + k) % n] for k in range(n)] + list(EXTRA.get(key, {}).get(rd.kind, ()))
            for b in ordered:
                qs.append({"kind": rd.kind, "skill": None, "jd_line": b.tests, "q": b.q, "key_points": list(b.key_points), "seconds": max(b.seconds, MIN_SECONDS.get(rd.kind, 0))})
        for q in qs:
            q["seconds"] = max(q["seconds"], MIN_SECONDS.get(rd.kind, 0)) if q["kind"] != "coding" else q["seconds"]
        candidates.append(qs)

    # Fit the interview to its length, in real minutes: coding problems take their own time; every other question
    # costs its answer time plus reading and follow-up. Everyone gets a screening question and one HR question; the
    # rest of the time goes to the field's core rounds, round-robin, so a 60-minute interview goes deeper.
    def cost(q: dict) -> int:
        return q["seconds"] + (0 if q["kind"] == "coding" else OVERHEAD_S)

    target = minutes * 60
    take = [0] * len(rounds_def)
    used = 0
    for i, rd in enumerate(rounds_def):
        if rd.kind == "coding":
            take[i] = len(candidates[i])
            used += sum(cost(q) for q in candidates[i])
        elif candidates[i]:
            take[i] = 1
            used += cost(candidates[i][0])
    screening_i = next((i for i, r in enumerate(rounds_def) if r.kind == "screening"), None)
    hr_i = len(rounds_def) - 1
    if screening_i is not None and minutes >= 45 and len(candidates[screening_i]) > 1:
        take[screening_i] = 2
        used += cost(candidates[screening_i][1])
    core = [i for i, r in enumerate(rounds_def) if r.kind != "coding" and i not in (screening_i, hr_i)]
    while core:
        moved = False
        for i in core:
            if take[i] < len(candidates[i]) and used + cost(candidates[i][take[i]]) <= target:
                used += cost(candidates[i][take[i]])
                take[i] += 1
                moved = True
        if not moved:
            break
    if take[hr_i] < min(2, len(candidates[hr_i])) and used + cost(candidates[hr_i][take[hr_i]]) <= target:
        used += cost(candidates[hr_i][take[hr_i]])
        take[hr_i] += 1

    rounds, questions = [], []
    for ri, rd in enumerate(rounds_def):
        chosen = candidates[ri] if rd.kind == "coding" else candidates[ri][: take[ri]]
        if not chosen:
            continue
        idx = len(rounds)
        rounds.append({"index": idx, "name": rd.name, "kind": rd.kind, "intro": rd.intro, "norm": norm_for(key, rd.kind)})
        for q in chosen:
            questions.append({**q, "round": idx, "round_name": rd.name})
    for i, q in enumerate(questions):
        q["id"] = f"q{i + 1}"
    return rounds, questions, key, level


def build_rounds(industry_key: str | None, title: str, company: str, jd_lines: list[str], evidence: dict | None, resume_projects: list[str], seed: int = 0) -> tuple[list[dict], list[dict], str]:
    """The 45-minute plan without trend questions (kept for callers that don't need the level)."""
    rounds, questions, key, _ = build_plan(industry_key, title, company, jd_lines, evidence, resume_projects, 45, None, None, None, seed)
    return rounds, questions, key


def industry_name(key: str) -> str:
    return INDUSTRIES[key].name if key in INDUSTRIES else key

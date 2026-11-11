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


def build_rounds(industry_key: str | None, title: str, company: str, jd_lines: list[str], evidence: dict | None, resume_projects: list[str], seed: int = 0) -> tuple[list[dict], list[dict], str]:
    """(rounds, questions, industry). seed rotates which bank questions are picked, so retakes differ."""
    key = industry_key if industry_key in ROUNDS else detect_industry(title, "\n".join(jd_lines))[0]
    rounds_def = ROUNDS.get(key) or ROUNDS["software"]
    rounds, questions = [], []
    jd_qs = _jd_questions(jd_lines, 3)
    repos = [r.get("name") for r in ((evidence or {}).get("github") or {}).get("top_repos", [])[:2] if r.get("name")]
    for ri, rd in enumerate(rounds_def):
        rounds.append({"index": ri, "name": rd.name, "kind": rd.kind, "intro": rd.intro})
        qs: list[dict] = []
        if rd.kind == "screening":
            qs.append({"kind": "screening", "skill": None, "jd_line": f"{title} at {company}", "q": rd.bank[0].q, "key_points": list(rd.bank[0].key_points), "seconds": rd.bank[0].seconds})
            qs.append({"kind": "screening", "skill": None, "jd_line": f"Why {company}", "q": f"Why do you want this {title} internship, and why {company}?", "key_points": [company.lower().split()[0] if company else "company", "role", "learn"], "seconds": 90})
        else:
            if rd.kind in ("technical",) and jd_qs:
                qs += jd_qs[:2]
                jd_qs = jd_qs[2:]
            if rd.kind in ("project", "portfolio"):
                for name in (repos or resume_projects)[:1]:
                    qs.append({"kind": "proof", "skill": None, "jd_line": f"Your project: {name}", "q": f"Walk me through {name}: the problem, your design choices, and one thing you'd do differently.", "key_points": ["problem", "chose", "because", "differently"], "seconds": 180})
            n = len(rd.bank)
            picks = [rd.bank[(seed + k) % n] for k in range(min(rd.take, n))]
            for b in picks:
                qs.append({"kind": rd.kind, "skill": None, "jd_line": b.tests, "q": b.q, "key_points": list(b.key_points), "seconds": b.seconds})
        for q in qs:
            questions.append({**q, "round": ri, "round_name": rd.name})
    # Short banks (or no job description): top up from the field's unused questions so every session has 8+.
    if len(questions) < 8:
        asked = {q["q"] for q in questions}
        spare = [(ri, rd, b) for ri, rd in enumerate(rounds_def) if rd.kind != "screening" for b in rd.bank if b.q not in asked]
        for ri, rd, b in spare[: 8 - len(questions)]:
            questions.append({"kind": rd.kind, "skill": None, "jd_line": b.tests, "q": b.q, "key_points": list(b.key_points), "seconds": b.seconds, "round": ri, "round_name": rd.name})
        questions.sort(key=lambda q: q["round"])
    questions = questions[:16]
    for i, q in enumerate(questions):
        q["id"] = f"q{i + 1}"
    return rounds, questions, key


def industry_name(key: str) -> str:
    return INDUSTRIES[key].name if key in INDUSTRIES else key

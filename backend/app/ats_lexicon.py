"""Industry profiles for ATS scoring: what each field's recruiters search for, and how a resume is judged there.

Every industry lists its keywords (canonical term -> aliases, ordered roughly by how often they appear in Indian
internship and fresher postings for that field), the sections a recruiter expects, the links that count as proof,
and how the four parts of the score are weighted. Tech terms reuse the shared skill lexicon (app.skills) so the
ATS score, the Matcher and the no-fabrication guard all agree on what "Python" or "React" means.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Industry:
    key: str
    name: str
    # Canonical terms from app.skills.SKILLS that count for this field (matched with the shared lexicon).
    tech: tuple[str, ...] = ()
    # Field-specific terms not in the shared lexicon: canonical -> aliases.
    terms: dict[str, tuple[str, ...]] = field(default_factory=dict)
    # The first `core` keywords (tech first, then terms) are what this field's recruiters search for most.
    core: int = 14
    # Sections a recruiter in this field expects: summary, skills, experience, projects, education, certifications, links.
    expects: tuple[str, ...] = ("skills", "education", "experience_or_projects")
    # Links that count as proof of work here (matched against the resume's links and text).
    proof_links: tuple[str, ...] = ()
    proof_label: str = ""
    # Score weights: keywords, impact, format, sections (sum to 1). With a job description, keywords weigh more.
    weights: tuple[float, float, float, float] = (0.40, 0.25, 0.20, 0.15)
    # Title words that identify a posting as this field.
    title_words: tuple[str, ...] = ()


SOFT_SKILLS: dict[str, tuple[str, ...]] = {
    "Communication": ("communication", "communication skills", "verbal and written"),
    "Teamwork": ("teamwork", "team player", "collaboration", "collaborative", "cross-functional"),
    "Leadership": ("leadership", "led a team", "team lead"),
    "Problem solving": ("problem solving", "problem-solving", "analytical thinking"),
    "Time management": ("time management", "deadlines", "prioritization", "prioritisation"),
    "Ownership": ("ownership", "self-starter", "self-motivated", "initiative"),
    "Attention to detail": ("attention to detail", "detail-oriented", "detail oriented"),
    "Adaptability": ("adaptability", "fast learner", "quick learner", "learn quickly"),
}

GITHUB = ("github.com", "gitlab.com")
CODING = ("leetcode.com", "codeforces.com", "codechef.com", "hackerrank.com", "kaggle.com")
PORTFOLIO = ("behance.net", "dribbble.com", "figma.com", "notion.site", "wixsite.com", "framer.website", "portfolio", "medium.com", "github.io", "vercel.app", "netlify.app")

INDUSTRIES: dict[str, Industry] = {
    i.key: i
    for i in [
        Industry(
            key="software",
            name="Software engineering",
            tech=(
                "Data Structures & Algorithms", "Python", "Java", "JavaScript", "C++", "SQL", "Git", "OOP", "REST APIs", "React",
                "Node.js", "TypeScript", "Linux", "Docker", "Unit Testing", "PostgreSQL", "MySQL", "MongoDB", "AWS", "CI/CD",
                "Microservices", "Next.js", "Django", "FastAPI", "Flask", "Express", "HTML/CSS", "Redis", "Kubernetes", "Go", "GraphQL",
            ),
            terms={
                "System design": ("system design", "low level design", "high level design", "lld", "hld"),
                "Debugging": ("debugging", "troubleshooting", "root cause"),
                "Code review": ("code review", "code reviews", "pull requests"),
                "Scalability": ("scalable", "scalability", "high availability", "performance optimization"),
                "Operating systems": ("operating systems",),
                "DBMS": ("dbms", "database management", "database design"),
                "Computer networks": ("computer networks", "networking", "tcp/ip", "http"),
                "Full stack": ("full stack", "full-stack", "fullstack"),
                "Backend": ("backend", "back-end", "server-side"),
                "Frontend": ("frontend", "front-end", "client-side"),
            },
            core=16,
            expects=("skills", "education", "experience_or_projects", "links"),
            proof_links=GITHUB + CODING,
            proof_label="GitHub or a coding profile (LeetCode, Codeforces)",
            title_words=("software", "sde", "developer", "backend", "frontend", "front end", "back end", "full stack", "fullstack", "web dev", "android", "ios", "devops", "sre", "programmer", "mobile app"),
        ),
        Industry(
            key="data_science",
            name="Data science & ML",
            tech=(
                "Python", "Machine Learning", "SQL", "Statistics", "Pandas", "NumPy", "scikit-learn", "Deep Learning", "PyTorch",
                "TensorFlow", "NLP", "Data Visualization", "Feature Engineering", "Model Evaluation", "Computer Vision", "LLMs",
                "Jupyter", "Matplotlib", "Hugging Face", "MLOps", "RAG", "Time Series", "XGBoost", "Spark", "Embeddings", "Git",
            ),
            terms={
                "Model deployment": ("model deployment", "deployed the model", "model serving", "inference api"),
                "Data preprocessing": ("data preprocessing", "data cleaning", "data wrangling", "preprocessing"),
                "Regression": ("regression", "linear regression", "logistic regression"),
                "Classification": ("classification", "classifier"),
                "Clustering": ("clustering", "k-means", "kmeans"),
                "Kaggle": ("kaggle",),
                "Research": ("research paper", "publication", "arxiv"),
            },
            core=16,
            expects=("skills", "education", "experience_or_projects", "links"),
            proof_links=GITHUB + ("kaggle.com", "huggingface.co"),
            proof_label="GitHub, Kaggle or Hugging Face",
            title_words=("data scien", "machine learning", "ml ", "ml engineer", "ai engineer", "ai/ml", "deep learning", "nlp", "computer vision", "research intern", "genai", "llm"),
        ),
        Industry(
            key="data_analytics",
            name="Data & business analytics",
            tech=("SQL", "Excel", "Power BI", "Tableau", "Python", "Data Analysis", "Data Visualization", "Statistics", "Pandas", "BigQuery", "Jupyter"),
            terms={
                "Dashboards": ("dashboard", "dashboards", "reporting dashboard"),
                "KPIs": ("kpi", "kpis", "metrics", "key performance indicators"),
                "Data cleaning": ("data cleaning", "data cleansing", "data quality", "data validation"),
                "Reporting": ("reporting", "reports", "mis report", "mis"),
                "A/B testing": ("a/b testing", "a/b test", "experimentation"),
                "Google Analytics": ("google analytics", "ga4"),
                "Pivot tables": ("pivot table", "pivot tables", "vlookup", "xlookup", "advanced excel"),
                "Stakeholder management": ("stakeholder", "stakeholders", "business teams"),
                "Insights": ("insights", "actionable insights", "trend analysis"),
                "Looker": ("looker", "looker studio", "data studio"),
            },
            core=14,
            expects=("skills", "education", "experience_or_projects"),
            proof_links=GITHUB + ("kaggle.com", "public.tableau.com", "novypro.com"),
            proof_label="a portfolio of dashboards (Tableau Public, GitHub)",
            title_words=("data analyst", "business analyst", "analytics", "bi analyst", "mis", "reporting analyst", "insights"),
        ),
        Industry(
            key="product",
            name="Product management",
            tech=("SQL", "Agile", "Excel"),
            terms={
                "Product roadmap": ("roadmap", "product roadmap", "product strategy"),
                "User research": ("user research", "user interviews", "customer interviews", "customer discovery"),
                "PRD": ("prd", "product requirements", "requirement documents", "specs"),
                "Metrics": ("metrics", "kpi", "kpis", "north star", "retention", "activation", "funnel"),
                "A/B testing": ("a/b testing", "a/b test", "experimentation"),
                "Prioritization": ("prioritization", "prioritisation", "rice", "moscow"),
                "Stakeholder management": ("stakeholder", "stakeholders", "cross-functional"),
                "User stories": ("user stories", "user story", "acceptance criteria"),
                "Jira": ("jira", "confluence", "linear"),
                "Wireframing": ("wireframe", "wireframes", "wireframing", "mockups"),
                "Figma": ("figma",),
                "Go-to-market": ("go-to-market", "gtm", "launch", "launched"),
                "Market research": ("market research", "competitive analysis", "competitor analysis", "market sizing"),
                "Product analytics": ("mixpanel", "amplitude", "product analytics", "google analytics"),
            },
            core=12,
            expects=("summary", "skills", "education", "experience_or_projects"),
            proof_links=("medium.com", "notion.site", "substack.com", "portfolio"),
            proof_label="case studies or product teardowns (Medium, Notion)",
            weights=(0.38, 0.30, 0.17, 0.15),
            title_words=("product manager", "product management", "apm", "associate product", "product analyst", "product intern", "product owner"),
        ),
        Industry(
            key="design",
            name="UI/UX & design",
            tech=("HTML/CSS",),
            terms={
                "Figma": ("figma",),
                "User research": ("user research", "user interviews", "usability testing", "user testing"),
                "Wireframing": ("wireframe", "wireframes", "wireframing", "low-fidelity", "lo-fi"),
                "Prototyping": ("prototype", "prototypes", "prototyping", "high-fidelity", "hi-fi"),
                "Design systems": ("design system", "design systems", "component library", "style guide"),
                "Interaction design": ("interaction design", "micro-interactions", "user flows", "user flow"),
                "Visual design": ("visual design", "ui design", "typography", "color theory", "layout"),
                "UX design": ("ux design", "user experience", "ux"),
                "Information architecture": ("information architecture", "card sorting", "sitemap"),
                "Accessibility": ("accessibility", "wcag", "a11y"),
                "Adobe XD": ("adobe xd",),
                "Photoshop": ("photoshop",),
                "Illustrator": ("illustrator",),
                "Personas": ("persona", "personas", "journey map", "user journey"),
                "Responsive design": ("responsive design", "mobile-first", "responsive"),
                "Motion design": ("after effects", "motion design", "animation"),
            },
            core=11,
            expects=("summary", "skills", "education", "experience_or_projects", "links"),
            proof_links=PORTFOLIO,
            proof_label="a portfolio link (Behance, Dribbble, a personal site)",
            weights=(0.30, 0.20, 0.20, 0.30),
            title_words=("designer", "ui/ux", "ux", "ui ", "product design", "graphic design", "visual design", "interaction design"),
        ),
        Industry(
            key="marketing",
            name="Marketing & growth",
            tech=("Excel",),
            terms={
                "SEO": ("seo", "search engine optimization", "search engine optimisation", "keyword research"),
                "Social media marketing": ("social media", "instagram", "linkedin marketing", "smm", "community management"),
                "Content marketing": ("content marketing", "content writing", "blog", "content strategy", "copywriting"),
                "Performance marketing": ("performance marketing", "paid ads", "google ads", "meta ads", "facebook ads", "sem", "ppc"),
                "Google Analytics": ("google analytics", "ga4", "google tag manager"),
                "Email marketing": ("email marketing", "newsletter", "mailchimp", "email campaigns"),
                "Campaigns": ("campaign", "campaigns", "campaign management"),
                "Brand": ("branding", "brand awareness", "brand marketing", "brand strategy"),
                "Market research": ("market research", "competitor analysis", "competitive analysis", "consumer research"),
                "Conversion rate": ("conversion rate", "ctr", "cpc", "cac", "roas", "engagement rate", "conversions"),
                "HubSpot": ("hubspot", "crm"),
                "Canva": ("canva",),
                "Influencer marketing": ("influencer", "influencer marketing", "creator partnerships"),
                "Growth": ("growth marketing", "growth hacking", "user acquisition", "lead generation"),
            },
            core=12,
            expects=("summary", "skills", "education", "experience_or_projects"),
            proof_links=PORTFOLIO + ("instagram.com", "youtube.com", "linkedin.com/in"),
            proof_label="a portfolio of campaigns or content",
            weights=(0.38, 0.30, 0.17, 0.15),
            title_words=("marketing", "seo", "content", "social media", "growth", "brand", "digital marketing", "copywrit", "communications"),
        ),
        Industry(
            key="finance",
            name="Finance & accounting",
            tech=("Excel",),
            terms={
                "Financial modeling": ("financial modeling", "financial modelling", "financial model", "three statement"),
                "Valuation": ("valuation", "dcf", "discounted cash flow", "comparable companies", "comps"),
                "Financial statements": ("financial statements", "balance sheet", "income statement", "cash flow statement", "p&l"),
                "Accounting": ("accounting", "bookkeeping", "journal entries", "ledger", "general ledger"),
                "Tally": ("tally", "tally erp", "tally prime"),
                "GST": ("gst", "gst returns", "indirect tax"),
                "Taxation": ("taxation", "income tax", "tds", "direct tax"),
                "Audit": ("audit", "auditing", "internal audit", "statutory audit"),
                "Budgeting": ("budgeting", "budget", "forecasting", "variance analysis"),
                "Equity research": ("equity research", "stock analysis", "investment research"),
                "Ratio analysis": ("ratio analysis", "financial analysis", "financial ratios"),
                "Reconciliation": ("reconciliation", "bank reconciliation", "accounts payable", "accounts receivable"),
                "Ind AS / IFRS": ("ind as", "ifrs", "gaap"),
                "Bloomberg": ("bloomberg", "capitaline", "prowess"),
                "VBA": ("vba", "macros"),
                "Certifications": ("cfa", "nism", "frm", "ca inter", "ca final", "acca", "cma"),
            },
            core=12,
            expects=("summary", "skills", "education", "experience_or_projects", "certifications"),
            proof_links=(),
            weights=(0.40, 0.25, 0.17, 0.18),
            title_words=("finance", "financial", "accounting", "accountant", "audit", "tax", "investment", "equity research", "credit", "treasury", "ca articleship", "banking"),
        ),
        Industry(
            key="consulting",
            name="Consulting & strategy",
            tech=("Excel", "SQL", "Power BI", "Data Analysis"),
            terms={
                "Problem solving": ("problem solving", "problem-solving", "structured thinking", "hypothesis"),
                "Market research": ("market research", "industry research", "market sizing", "secondary research"),
                "Business analysis": ("business analysis", "business case", "requirements gathering"),
                "PowerPoint": ("powerpoint", "presentations", "slide decks", "deck"),
                "Stakeholder management": ("stakeholder", "stakeholders", "client", "clients"),
                "Strategy": ("strategy", "strategic", "go-to-market", "growth strategy"),
                "Competitive analysis": ("competitive analysis", "competitor analysis", "benchmarking"),
                "Process improvement": ("process improvement", "process optimization", "operational efficiency"),
                "Case competitions": ("case competition", "case study competition", "case challenge"),
                "Financial analysis": ("financial analysis", "cost-benefit", "unit economics"),
            },
            core=10,
            expects=("summary", "skills", "education", "experience_or_projects"),
            weights=(0.36, 0.32, 0.17, 0.15),
            title_words=("consult", "strategy", "business analyst", "associate", "management trainee", "research analyst"),
        ),
        Industry(
            key="sales",
            name="Sales & business development",
            tech=("Excel",),
            terms={
                "Lead generation": ("lead generation", "leads", "prospecting", "outbound"),
                "CRM": ("crm", "salesforce", "hubspot", "zoho crm"),
                "Business development": ("business development", "bd", "partnerships"),
                "Client relationship": ("client relationship", "relationship management", "account management", "customer relationship"),
                "Negotiation": ("negotiation", "negotiated", "closing deals"),
                "Cold calling": ("cold calling", "cold calls", "cold email", "cold outreach"),
                "B2B sales": ("b2b", "b2b sales", "enterprise sales", "saas sales"),
                "Revenue": ("revenue", "sales targets", "quota", "pipeline"),
                "Customer acquisition": ("customer acquisition", "onboarded clients", "new clients"),
                "Presentation": ("presentations", "product demos", "pitching", "pitch"),
            },
            core=10,
            expects=("summary", "skills", "education", "experience_or_projects"),
            weights=(0.34, 0.36, 0.15, 0.15),
            title_words=("sales", "business development", "bde", "bd ", "account executive", "inside sales", "pre-sales", "partnership"),
        ),
        Industry(
            key="hr",
            name="Human resources",
            tech=("Excel",),
            terms={
                "Recruitment": ("recruitment", "recruiting", "talent acquisition", "hiring"),
                "Sourcing": ("sourcing", "screening", "candidate sourcing", "job portals"),
                "Onboarding": ("onboarding", "induction", "orientation"),
                "Employee engagement": ("employee engagement", "engagement activities", "employee experience"),
                "HRIS": ("hris", "hrms", "workday", "darwinbox", "zoho people", "successfactors"),
                "Payroll": ("payroll", "attendance", "compensation", "benefits"),
                "Interview coordination": ("interview scheduling", "interview coordination", "scheduling interviews"),
                "Employer branding": ("employer branding", "campus hiring", "campus recruitment"),
                "Labour laws": ("labour law", "labor law", "compliance", "pf", "esi", "posh"),
                "Performance management": ("performance management", "appraisal", "appraisals", "kra"),
                "MS Office": ("ms office", "microsoft office", "google workspace"),
            },
            core=10,
            expects=("summary", "skills", "education", "experience_or_projects"),
            weights=(0.36, 0.30, 0.18, 0.16),
            title_words=("hr", "human resource", "talent acquisition", "recruit", "people operations", "people ops"),
        ),
        Industry(
            key="core_engineering",
            name="Core engineering (mech / electrical / civil / electronics)",
            tech=("MATLAB", "C", "Python"),
            terms={
                "AutoCAD": ("autocad", "auto cad"),
                "SolidWorks": ("solidworks", "solid works"),
                "CATIA": ("catia",),
                "ANSYS": ("ansys", "fea", "finite element", "cfd", "computational fluid dynamics"),
                "CAD/CAM": ("cad", "cam", "creo", "nx", "fusion 360", "3d modeling", "3d modelling"),
                "Manufacturing": ("manufacturing", "production", "machining", "cnc", "assembly line"),
                "PLC": ("plc", "scada", "automation", "hmi"),
                "Embedded systems": ("embedded", "embedded systems", "microcontroller", "arduino", "raspberry pi", "stm32", "esp32"),
                "Circuit design": ("circuit design", "pcb", "pcb design", "altium", "kicad", "eagle"),
                "VLSI": ("vlsi", "verilog", "vhdl", "fpga", "systemverilog"),
                "IoT": ("iot", "internet of things", "sensors"),
                "Quality control": ("quality control", "quality assurance", "qc", "inspection", "six sigma", "lean", "kaizen", "5s"),
                "Civil design": ("staad", "staad pro", "etabs", "revit", "structural analysis", "surveying", "estimation"),
                "Thermal": ("thermodynamics", "heat transfer", "hvac", "thermal analysis"),
                "Project management": ("project management", "site execution", "planning", "primavera", "ms project"),
            },
            core=12,
            expects=("skills", "education", "experience_or_projects"),
            weights=(0.40, 0.25, 0.18, 0.17),
            title_words=("mechanical", "electrical", "civil", "electronics", "ece", "eee", "embedded", "vlsi", "design engineer", "production", "manufacturing", "graduate engineer trainee", "get "),
        ),
        Industry(
            key="operations",
            name="Operations & supply chain",
            tech=("Excel", "SQL", "Power BI"),
            terms={
                "Supply chain": ("supply chain", "scm"),
                "Logistics": ("logistics", "last mile", "fleet", "shipping", "dispatch"),
                "Inventory management": ("inventory", "inventory management", "stock management", "warehouse", "warehousing"),
                "Procurement": ("procurement", "purchasing", "sourcing", "vendor management", "vendors"),
                "ERP": ("erp", "sap", "oracle erp", "sap mm", "sap sd"),
                "Process improvement": ("process improvement", "process optimization", "lean", "six sigma", "kaizen"),
                "Demand planning": ("demand planning", "forecasting", "s&op"),
                "Operations": ("operations", "ops", "daily operations", "sop", "sops"),
                "KPIs": ("kpi", "kpis", "sla", "slas", "tat", "turnaround time"),
                "Cost reduction": ("cost reduction", "cost savings", "cost optimisation", "cost optimization"),
            },
            core=10,
            expects=("summary", "skills", "education", "experience_or_projects"),
            weights=(0.38, 0.30, 0.17, 0.15),
            title_words=("operations", "supply chain", "logistics", "procurement", "warehouse", "planning", "category", "ops "),
        ),
    ]
}

DEFAULT_INDUSTRY = "software"

# Role-aware grading. A recruiter searches for one role ("backend developer intern"), not for every keyword in a
# field, so without a job description a resume is graded on the field's fundamentals plus the role it fits best.
# Each track: (label, title words that point to it, keywords in search order). Fields without tracks use their
# whole list.
FUNDAMENTALS: dict[str, tuple[str, ...]] = {
    "software": ("Data Structures & Algorithms", "Git", "SQL", "OOP"),
    "data_science": ("Python", "SQL", "Statistics", "Machine Learning", "Git"),
    "data_analytics": ("SQL", "Excel", "Data Analysis", "Data Visualization"),
    "core_engineering": (),
}
ROLE_TRACKS: dict[str, dict[str, tuple[str, tuple[str, ...], tuple[str, ...]]]] = {
    "software": {
        "backend": ("Backend developer", ("backend", "back-end", "server", "api"), ("REST APIs", "Python", "Java", "PostgreSQL", "MySQL", "Docker", "Unit Testing", "Linux", "Microservices", "Redis", "Django", "FastAPI", "Flask", "Spring Boot", "System design", "Backend")),
        "frontend": ("Frontend developer", ("frontend", "front-end", "ui developer", "web developer"), ("JavaScript", "TypeScript", "React", "Next.js", "HTML/CSS", "REST APIs", "Unit Testing", "Frontend", "Redux")),
        "fullstack": ("Full-stack developer", ("full stack", "full-stack", "fullstack", "mern", "web app"), ("JavaScript", "React", "Node.js", "Express", "REST APIs", "MongoDB", "PostgreSQL", "TypeScript", "HTML/CSS", "Docker", "Full stack")),
        "mobile": ("Mobile developer", ("android", "ios", "mobile", "flutter", "app developer"), ("Android", "Kotlin", "Java", "Flutter", "Swift", "React Native", "Firebase", "REST APIs", "Unit Testing")),
        "devops": ("DevOps / cloud engineer", ("devops", "sre", "cloud", "infrastructure", "platform"), ("Linux", "Docker", "Kubernetes", "AWS", "CI/CD", "Terraform", "Bash", "Python", "Microservices", "Scalability", "Debugging")),
        "sde": ("Software engineer (generalist)", ("sde", "software engineer", "software developer", "programmer"), ("Java", "C++", "Python", "Operating systems", "DBMS", "Computer networks", "REST APIs", "Unit Testing", "Debugging", "Linux")),
    },
    "data_science": {
        "ml": ("Data scientist / ML", ("data scientist", "machine learning", "ml engineer", "data science"), ("Pandas", "NumPy", "scikit-learn", "Feature Engineering", "Model Evaluation", "Data Visualization", "XGBoost", "Regression", "Classification", "Jupyter", "Data preprocessing")),
        "nlp": ("NLP / LLM engineer", ("nlp", "llm", "genai", "generative", "language model"), ("Deep Learning", "PyTorch", "NLP", "LLMs", "Hugging Face", "RAG", "Embeddings", "Model Evaluation", "Model deployment", "TensorFlow")),
        "cv": ("Computer vision engineer", ("computer vision", "vision", "image", "cv engineer"), ("Deep Learning", "PyTorch", "TensorFlow", "Computer Vision", "OpenCV", "Model Evaluation", "Data preprocessing", "Model deployment")),
        "mlops": ("MLOps / data engineer", ("mlops", "data engineer", "pipeline", "platform"), ("MLOps", "Model deployment", "Docker", "Spark", "Airflow", "AWS", "Kafka", "CI/CD", "Data preprocessing")),
    },
    "data_analytics": {
        "bi": ("BI / reporting analyst", ("bi", "business intelligence", "reporting", "mis"), ("Power BI", "Tableau", "Dashboards", "KPIs", "Reporting", "Pivot tables", "Data cleaning", "Looker")),
        "product": ("Product / business analyst", ("product analyst", "business analyst", "growth", "analytics"), ("Python", "Statistics", "A/B testing", "Google Analytics", "Insights", "Stakeholder management", "BigQuery", "Pandas")),
    },
    "core_engineering": {
        "mech_design": ("Mechanical design engineer", ("mechanical", "design engineer", "cad", "product design"), ("AutoCAD", "SolidWorks", "CATIA", "ANSYS", "CAD/CAM", "Thermal", "MATLAB")),
        "manufacturing": ("Manufacturing / production engineer", ("manufacturing", "production", "quality", "plant"), ("Manufacturing", "Quality control", "CAD/CAM", "AutoCAD", "Project management")),
        "electronics": ("Electrical / electronics engineer", ("electrical", "electronics", "embedded", "vlsi", "iot"), ("C", "Embedded systems", "Circuit design", "PLC", "MATLAB", "IoT", "VLSI", "Python")),
        "civil": ("Civil engineer", ("civil", "structural", "site engineer", "construction"), ("AutoCAD", "Civil design", "Project management", "Quality control")),
    },
}

# Verbs that open a strong bullet. Ordered by family only for readability.
ACTION_VERBS = frozenset(
    ["accelerated", "achieved", "acquired", "analysed", "analyzed", "architected", "assembled", "audited", "authored", "automated", "benchmarked", "boosted", "built", "calculated", "campaigned", "championed", "closed", "coached", "coded", "collaborated", "compiled", "computed", "conceived", "conceptualized", "conducted", "configured", "consolidated", "constructed", "contributed", "converted", "coordinated", "created", "curated", "cut", "debugged", "decreased", "defined", "delivered", "deployed", "designed", "developed", "devised", "diagnosed", "directed", "doubled", "drafted", "drove", "earned", "edited", "eliminated", "enabled", "engineered", "enhanced", "established", "estimated", "evaluated", "executed", "expanded", "experimented", "extracted", "fabricated", "facilitated", "finalized", "forecasted", "formulated", "founded", "generated", "grew", "guided", "halved", "headed", "identified", "illustrated", "implemented", "improved", "increased", "initiated", "innovated", "inspected", "installed", "instituted", "integrated", "interviewed", "introduced", "investigated", "launched", "led", "leveraged", "machined", "managed", "mapped", "maximized", "measured", "mentored", "migrated", "minimized", "modeled", "modelled", "modernized", "monitored", "negotiated", "onboarded", "operated", "optimised", "optimized", "orchestrated", "organised", "organized", "oversaw", "parsed", "partnered", "piloted", "pioneered", "planned", "presented", "prioritized", "processed", "produced", "programmed", "prototyped", "published", "raised", "ranked", "rebuilt", "recruited", "redesigned", "reduced", "refactored", "remodeled", "reorganized", "reported", "researched", "resolved", "restructured", "revamped", "reviewed", "saved", "scaled", "scheduled", "scripted", "secured", "shipped", "simplified", "simulated", "sold", "solved", "sourced", "spearheaded", "standardized", "started", "streamlined", "strengthened", "structured", "supervised", "surveyed", "synthesized", "taught", "tested", "tracked", "trained", "transformed", "translated", "tripled", "troubleshot", "tuned", "unified", "upgraded", "validated", "visualized", "won", "wrote", "served", "performed", "forecast", "predicted", "classified", "clustered", "scraped", "crawled", "visualised", "cleaned", "labelled", "labeled", "annotated", "wrangled", "queried", "indexed", "cached", "containerised", "containerized", "dockerized", "hosted", "released", "maintained", "extended", "ported", "documented", "demonstrated", "hypothesized", "prepared", "ran", "owned", "crafted", "animated", "filmed", "coded", "fine-tuned", "finetuned"]
)

# Openers and phrases that tell a recruiter what you were assigned, not what you did.
WEAK_PHRASES = (
    "responsible for", "worked on", "helped", "helping", "assisted", "involved in", "participated in", "duties included",
    "tasked with", "in charge of", "handled", "was part of", "exposure to", "familiar with", "various", "etc",
)
CLICHES = ("hardworking", "hard-working", "team player", "go-getter", "synergy", "think outside the box", "results-driven", "dynamic individual", "passionate about everything", "self-motivated individual")

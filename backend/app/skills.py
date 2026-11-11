"""Skill lexicon: the shared vocabulary for matching, explanations and the no-fabrication guard.

Each canonical skill maps to the aliases that should count as the same thing. Matching is
case-insensitive and boundary-aware so "R" does not match inside "React" and "Go" needs context.
"""

import re
from functools import lru_cache

SKILLS: dict[str, list[str]] = {
    # Languages
    "Python": ["python", "python3"],
    "R": ["r programming", "r language", "rstudio", "tidyverse"],
    "SQL": ["sql", "t-sql", "pl/sql"],
    "Java": ["java"],
    "JavaScript": ["javascript", "js", "es6"],
    "TypeScript": ["typescript", "ts"],
    "C++": ["c++", "cpp"],
    "C": ["c language", "ansi c"],
    "C#": ["c#", "csharp"],
    "Go": ["golang", "go lang"],
    "Rust": ["rust"],
    "Scala": ["scala"],
    "Julia": ["julia"],
    "MATLAB": ["matlab"],
    "Bash": ["bash", "shell scripting", "shell script"],
    # ML / DS
    "Machine Learning": ["machine learning", "ml"],
    "Deep Learning": ["deep learning", "dl"],
    "NLP": ["nlp", "natural language processing"],
    "Computer Vision": ["computer vision", "cv models", "image classification", "object detection"],
    "LLMs": ["llm", "llms", "large language model", "large language models", "genai", "generative ai"],
    "RAG": ["rag", "retrieval augmented generation", "retrieval-augmented generation"],
    "Agents": ["ai agents", "agentic", "multi-agent", "multi agent"],
    "Reinforcement Learning": ["reinforcement learning"],
    "Statistics": ["statistics", "statistical modeling", "statistical modelling", "hypothesis testing", "a/b testing"],
    "Time Series": ["time series", "forecasting"],
    "Recommender Systems": ["recommender system", "recommender systems", "recommendation system", "recommendation engine", "recommender"],
    "Feature Engineering": ["feature engineering"],
    "Data Analysis": ["data analysis", "exploratory data analysis", "eda", "data analytics"],
    "Data Visualization": ["data visualization", "data visualisation"],
    "scikit-learn": ["scikit-learn", "sklearn", "scikit learn"],
    "TensorFlow": ["tensorflow", "tf2"],
    "Keras": ["keras"],
    "PyTorch": ["pytorch", "torch"],
    "JAX": ["jax"],
    "XGBoost": ["xgboost"],
    "LightGBM": ["lightgbm"],
    "Hugging Face": ["hugging face", "huggingface", "transformers library"],
    "Transformers": ["transformer models", "transformers", "bert", "gpt"],
    "LangChain": ["langchain"],
    "LangGraph": ["langgraph"],
    "LlamaIndex": ["llamaindex", "llama index"],
    "OpenCV": ["opencv"],
    "spaCy": ["spacy"],
    "NLTK": ["nltk"],
    "Pandas": ["pandas"],
    "NumPy": ["numpy"],
    "SciPy": ["scipy"],
    "Matplotlib": ["matplotlib"],
    "Seaborn": ["seaborn"],
    "Plotly": ["plotly"],
    "Jupyter": ["jupyter", "jupyter notebook", "notebooks"],
    "Tableau": ["tableau"],
    "Power BI": ["power bi", "powerbi"],
    "Excel": ["excel", "spreadsheets"],
    "Spark": ["spark", "pyspark", "apache spark"],
    "Hadoop": ["hadoop"],
    "Airflow": ["airflow", "apache airflow"],
    "dbt": ["dbt"],
    "Kafka": ["kafka"],
    "MLflow": ["mlflow"],
    "Weights & Biases": ["weights & biases", "wandb", "weights and biases"],
    "MLOps": ["mlops", "ml ops"],
    "Vector Databases": ["vector database", "vector databases", "pgvector", "pinecone", "faiss", "chroma", "weaviate", "qdrant"],
    "Embeddings": ["embeddings", "embedding"],
    "Prompt Engineering": ["prompt engineering"],
    "Model Evaluation": ["model evaluation", "evals", "evaluation metrics"],
    # Backend / web
    "Flask": ["flask"],
    "FastAPI": ["fastapi"],
    "Django": ["django"],
    "Node.js": ["node.js", "nodejs", "node"],
    "Express": ["express.js", "expressjs"],
    "React": ["react", "react.js", "reactjs"],
    "Next.js": ["next.js", "nextjs"],
    "HTML/CSS": ["html", "css", "tailwind", "tailwindcss"],
    "REST APIs": ["rest api", "rest apis", "restful", "rest"],
    "GraphQL": ["graphql"],
    "gRPC": ["grpc"],
    "Microservices": ["microservices", "microservice"],
    # Data stores
    "PostgreSQL": ["postgresql", "postgres", "psql"],
    "MySQL": ["mysql"],
    "MongoDB": ["mongodb", "mongo"],
    "Redis": ["redis"],
    "SQLite": ["sqlite"],
    "BigQuery": ["bigquery"],
    "Snowflake": ["snowflake"],
    "Elasticsearch": ["elasticsearch", "opensearch"],
    # Infra
    "Docker": ["docker", "dockerized", "dockerised", "dockerfile", "containers", "containerized", "containerization"],
    "Kubernetes": ["kubernetes", "k8s", "helm"],
    "AWS": ["aws", "amazon web services", "sagemaker", "ec2", "s3", "lambda"],
    "GCP": ["gcp", "google cloud", "vertex ai"],
    "Azure": ["azure"],
    "Linux": ["linux", "unix"],
    "Git": ["git", "github", "gitlab"],
    "CI/CD": ["ci/cd", "github actions", "jenkins", "continuous integration"],
    "Terraform": ["terraform"],
    # Practices
    "Unit Testing": ["unit testing", "pytest", "unittest", "jest"],
    "Data Structures & Algorithms": ["data structures", "algorithms", "dsa"],
    "OOP": ["object oriented", "object-oriented", "oop"],
    "Agile": ["agile", "scrum"],
}

_BOUNDARY_L = r"(?<![A-Za-z0-9+#./])"
_BOUNDARY_R = r"(?![A-Za-z0-9+#]|\.[A-Za-z])"
# Short / ambiguous aliases only count when written with this exact casing ("ML", not "ml" in "html").
_EXACT_CASE = {
    "ml": "ML", "dl": "DL", "ts": "TS", "js": "JS", "rest": "REST", "node": "Node", "lambda": "Lambda",
    "s3": "S3", "ec2": "EC2", "gpt": "GPT", "eda": "EDA", "rag": "RAG", "go lang": "Go lang",
    "rust": "Rust", "julia": "Julia",
}
# Canonical names that are also everyday words/letters: only their aliases count ("golang", "R programming").
_ALIASES_ONLY = {"Go", "R", "C"}


@lru_cache
def _patterns() -> list[tuple[str, re.Pattern[str]]]:
    pats: list[tuple[str, re.Pattern[str]]] = []
    for canonical, aliases in SKILLS.items():
        terms = set(aliases) if canonical in _ALIASES_ONLY else {canonical.lower(), *aliases}
        for term in sorted(terms, key=len, reverse=True):
            if term in _EXACT_CASE:
                pat = re.compile(_BOUNDARY_L + re.escape(_EXACT_CASE[term]) + _BOUNDARY_R)
            else:
                pat = re.compile(_BOUNDARY_L + re.escape(term) + _BOUNDARY_R, re.IGNORECASE)
            pats.append((canonical, pat))
        if canonical in _ALIASES_ONLY:
            # The bare letter / word counts in a programming context: "written in Go", "using C", "with R and".
            pats.append((canonical, re.compile(r"\b(?:in|using|with|and|or)\s+" + canonical + r"(?![A-Za-z0-9+#&'/]|\.[A-Za-z])(?!\s+(?:grade|section|block|wing|level|ahead|live|to))")))
    return pats


def extract_skills(text: str) -> list[str]:
    """Canonical skills mentioned in text, in first-seen order."""
    if not text:
        return []
    found: dict[str, int] = {}
    for canonical, pat in _patterns():
        m = pat.search(text)
        if m and (canonical not in found or m.start() < found[canonical]):
            found[canonical] = m.start()
    return [k for k, _ in sorted(found.items(), key=lambda kv: kv[1])]


def canonicalize(skill: str) -> str:
    hits = extract_skills(skill)
    return hits[0] if hits else skill.strip()


# A skills taxonomy: tools in one family are close substitutes, so a PyTorch developer is a partial match for a
# TensorFlow role (they share the concepts and learn the other quickly). Names are this module's canonical forms.
SKILL_FAMILIES: dict[str, set[str]] = {
    "deep learning frameworks": {"PyTorch", "TensorFlow", "Keras", "JAX"},
    "classical ML": {"scikit-learn", "XGBoost", "LightGBM"},
    "LLM tooling": {"LangChain", "LlamaIndex", "Hugging Face", "OpenAI API", "LLMs", "RAG"},
    "frontend frameworks": {"React", "Angular", "Vue", "Svelte", "Next.js"},
    "Node backends": {"Node.js", "Express", "NestJS"},
    "Python web": {"Django", "Flask", "FastAPI"},
    "JVM languages": {"Java", "Kotlin", "Scala"},
    "systems languages": {"C++", "C", "Rust", "Go"},
    "relational databases": {"PostgreSQL", "MySQL", "SQL Server", "Oracle", "SQLite"},
    "NoSQL": {"MongoDB", "DynamoDB", "Cassandra", "Redis", "Firebase"},
    "cloud": {"AWS", "GCP", "Azure"},
    "containers": {"Docker", "Kubernetes"},
    "CI/CD": {"CI/CD", "GitHub Actions", "Jenkins", "GitLab"},
    "BI tools": {"Tableau", "Power BI", "Looker"},
    "mobile": {"Android", "iOS", "Flutter", "React Native", "Swift"},
    "big data": {"Spark", "Hadoop", "Hive", "Kafka", "Airflow"},
    "design tools": {"Figma", "Adobe XD", "Sketch"},
}
_FAMILY_OF: dict[str, str] = {m.lower(): fam for fam, members in SKILL_FAMILIES.items() for m in members}
ADJACENT_CREDIT = 0.6


def adjacent(resume_skills: list[str], job_skills: list[str]) -> list[tuple[str, str]]:
    """(job skill, the candidate's sibling skill) for job skills they lack but have a close substitute for."""
    have = {s.lower() for s in resume_skills}
    by_family: dict[str, str] = {}
    for s in resume_skills:
        fam = _FAMILY_OF.get(s.lower())
        if fam:
            by_family.setdefault(fam, s)
    out = []
    for j in job_skills:
        if j.lower() in have:
            continue
        fam = _FAMILY_OF.get(j.lower())
        if fam and fam in by_family:
            out.append((j, by_family[fam]))
    return out


def skill_overlap(resume_skills: list[str], job_skills: list[str]) -> tuple[list[str], list[str], float]:
    """(strengths, gaps, 0-100 coverage of the job's skills). A gap the candidate has a close substitute for (same
    family in the taxonomy) still counts as a gap, but earns partial coverage."""
    have = {s.lower() for s in resume_skills}
    strengths = [s for s in job_skills if s.lower() in have]
    gaps = [s for s in job_skills if s.lower() not in have]
    if not job_skills:
        return [], [], 50.0
    near = len(adjacent(resume_skills, job_skills))
    return strengths, gaps, 100.0 * (len(strengths) + ADJACENT_CREDIT * near) / len(job_skills)


# A heading-like line that starts the part of a posting describing the job ("Requirements",
# "What you'll do:"). Only short lines count, so prose like "You'll have direct access..." doesn't.
_HEADING = re.compile(
    r"^\s*(?:#+\s*|\*\*)?(?:what (?:you('|’)?ll|you will) (?:do|need|bring|work on|be doing)|what we('|’)?re looking for|"
    r"(?:key |your |main )?responsibilit\w*|requirements?|(?:minimum |basic |preferred )?qualifications?|"
    r"(?:required |must[- ]have )?skills( required)?|about the (?:role|job|internship|position)|the role|role overview|"
    r"who you are|you have|job description|your role|eligibility|what you'll learn|in this role)\b",
    re.IGNORECASE,
)
_BOILERPLATE = re.compile(
    r"equal (employment )?opportunity|eeo|reasonable accommodation|privacy (notice|policy)|benefits include|"
    r"we offer|perks|e-verify|background check|applicant|diversity|inclusion|salary range|compensation",
    re.IGNORECASE,
)


def role_digest(description: str, limit: int = 2500) -> str:
    """The part of a posting that describes the job: real postings open with company boilerplate and
    end with benefits / EEO text, which dilutes embeddings and wastes LLM tokens."""
    lines = [ln.strip() for ln in (description or "").splitlines() if ln.strip()]
    start = next((i for i, ln in enumerate(lines) if len(ln) <= 90 and _HEADING.match(ln)), 0)
    kept = [ln for ln in lines[start:] if not _BOILERPLATE.search(ln)]
    return re.sub(r"[ \t]+", " ", "\n".join(kept))[:limit]


def job_embedding_text(title: str, company: str, description: str) -> str:
    skills = extract_skills(f"{title}\n{description}")
    return f"{title} at {company}\nSkills: {', '.join(skills)}\n{role_digest(description, 2000)}"

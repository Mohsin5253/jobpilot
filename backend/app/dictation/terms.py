"""Spellings of technical terms speech models get almost right (GitHub, PostgreSQL, CI/CD...)."""

import re

# Spoken-English mishearings of technical terms, and spellings Whisper often gets almost right.
FIXES = {
    r"\bjit ?hub\b": "GitHub", r"\bgit ?hub\b": "GitHub", r"\bgit ?lab\b": "GitLab", r"\bci[- ]cd\b": "CI/CD",
    r"\bpost ?gre ?sql\b": "PostgreSQL", r"\bpost ?gres\b": "Postgres", r"\bmy ?sql\b": "MySQL", r"\bno ?sql\b": "NoSQL",
    r"\bjava ?script\b": "JavaScript", r"\btype ?script\b": "TypeScript", r"\bnode ?(?:\.|dot)? ?js\b": "Node.js",
    r"\bnext ?(?:\.|dot)? ?js\b": "Next.js", r"\breact ?(?:\.|dot)? ?js\b": "React", r"\bfast ?api\b": "FastAPI",
    r"\bpy ?torch\b": "PyTorch", r"\btensor ?flow\b": "TensorFlow", r"\bscikit[- ]?learn\b": "scikit-learn", r"\bnum ?py\b": "NumPy",
    r"\bpower ?bi\b": "Power BI", r"\bk8s\b": "Kubernetes", r"\bkuber ?netes\b": "Kubernetes", r"\bdev ?ops\b": "DevOps",
    r"\bml ?ops\b": "MLOps", r"\bllms\b": "LLMs", r"\bllm\b": "LLM", r"\brest ?apis?\b": lambda m: "REST APIs" if m.group(0).lower().endswith("s") else "REST API",
    r"\bjson\b": "JSON", r"\bsql\b": "SQL", r"\baws\b": "AWS", r"\bgcp\b": "GCP", r"\bdsa\b": "DSA", r"\boop\b": "OOP",
    r"\bui ?/? ?ux\b": "UI/UX", r"\bseo\b": "SEO", r"\broas\b": "ROAS", r"\bctr\b": "CTR", r"\bkpis?\b": lambda m: m.group(0).upper().replace("KPIS", "KPIs"),
    r"\bci ?/? ?cd\b|\bc ?i ?c ?d\b": "CI/CD", r"\bpost ?gres ?(?:cal|kel|kwel|sequel|q ?l|s ?q ?l)\b": "PostgreSQL",
    r"\bmy ?sequel\b": "MySQL", r"\bmongo ?db\b": "MongoDB", r"\bfire ?base\b": "Firebase", r"\bgraph ?ql\b": "GraphQL",
    r"\bc ?sharp\b": "C#", r"\bc ?plus ?plus\b": "C++", r"\bdot ?net\b": ".NET", r"\bexpress ?(?:\.|dot)? ?js\b": "Express.js",
    r"\bspring ?boot\b": "Spring Boot", r"\btail ?wind\b": "Tailwind", r"\bopen ?ai\b": "OpenAI", r"\blang ?chain\b": "LangChain",
    r"\bhugging ?face\b": "Hugging Face", r"\bmat ?plot ?lib\b": "Matplotlib", r"\bjupiter notebook\b": "Jupyter notebook",
    r"\btablo\b": "Tableau", r"\bfig ?ma\b": "Figma", r"\bj ?query\b": "jQuery", r"\bvs ?code\b": "VS Code",
    r"\bgst\b": "GST", r"\btds\b": "TDS", r"\bdcf\b": "DCF", r"\bcgpa\b": "CGPA", r"\bb\. ?tech\b": "B.Tech",
}
_FIXES = [(re.compile(k, re.I), v) for k, v in FIXES.items()]


def polish(text: str) -> str:
    """Correct technical terms' spelling and casing (GitHub, PostgreSQL, CI/CD...), which matter in an interview answer."""
    for rx, rep in _FIXES:
        text = rx.sub(rep, text)
    return text

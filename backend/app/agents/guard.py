"""No-fabrication guard for anything written on the candidate's behalf.

Checks a rewritten bullet against its source:
  * fabricated  - a specific tool/skill that appears nowhere in the resume
  * misattributed - a tool that is in the resume but not in this bullet's own context
                    (e.g. moving "Docker" from project A into a bullet about project B)
  * numbers     - any figure (metric, count, %) that is not in the source bullet
Broad concepts ("Machine Learning", "Data Analysis") are allowed as rephrasing of concrete work.
"""

import re
from dataclasses import dataclass, field

from app.schemas import ResumeData
from app.skills import extract_skills

GENERIC = {
    "Machine Learning", "Deep Learning", "Data Analysis", "Data Visualization", "Statistics",
    "Feature Engineering", "Model Evaluation", "REST APIs", "OOP", "Agile", "Data Structures & Algorithms",
    "Embeddings", "Prompt Engineering", "Microservices", "Time Series", "NLP", "Computer Vision", "LLMs",
}
_NUM = re.compile(r"(?<![A-Za-z\d.,])(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*([kKmM](?![a-zA-Z])|[xX%])?")
_SCALE = {"k": 1_000, "m": 1_000_000}


def _numbers(text: str) -> set[str]:
    """Figures as canonical values, so "40k", "40K" and "40,000" are the same number but 12% != 12."""
    out = set()
    for m in _NUM.finditer(text):
        value = float(m.group(1).replace(",", ""))
        suffix = (m.group(2) or "").lower()
        value *= _SCALE.get(suffix, 1)
        unit = suffix if suffix in ("%", "x") else ""
        out.add(f"{value:g}{unit}")
    return out


@dataclass
class BulletVerdict:
    ok: bool
    fabricated: list[str] = field(default_factory=list)
    misattributed: list[str] = field(default_factory=list)
    numbers: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"fabricated": self.fabricated, "misattributed": self.misattributed, "numbers": self.numbers}


def bullet_contexts(resume: ResumeData) -> dict[str, str]:
    """source_id -> the text a rewrite of that bullet may draw on (bullet + its role/project header)."""
    ctx: dict[str, str] = {}
    for i, e in enumerate(resume.experience):
        for j, b in enumerate(e.bullets):
            ctx[f"exp{i}.b{j}"] = f"{e.title} {e.organization}\n{b}"
    for i, p in enumerate(resume.projects):
        for j, b in enumerate(p.bullets):
            ctx[f"proj{i}.b{j}"] = f"{p.name} {' '.join(p.tech)}\n{b}"
    for i, a in enumerate(resume.additional):
        if a.details.strip():
            ctx[f"add{i}"] = f"{a.skill}\n{a.details}"  # self-reported to the Interviewer, in the user's words
    return ctx


def resume_skillset(resume: ResumeData, resume_text: str = "") -> set[str]:
    return set(extract_skills(resume_text + "\n" + resume.model_dump_json())) | set(resume.skills)


def check_bullet(rewritten: str, source_context: str, resume_skills: set[str]) -> BulletVerdict:
    used = set(extract_skills(rewritten)) - GENERIC
    in_source = set(extract_skills(source_context))
    fabricated = sorted(s for s in used if s not in resume_skills)
    misattributed = sorted(s for s in used if s in resume_skills and s not in in_source)
    bullet_line = source_context.split("\n", 1)[-1]
    new_numbers = sorted(_numbers(rewritten) - _numbers(bullet_line))
    return BulletVerdict(ok=not (fabricated or misattributed or new_numbers), fabricated=fabricated, misattributed=misattributed, numbers=new_numbers)


def check_freeform(text: str, resume_skills: set[str]) -> list[str]:
    """For emails / notes: specific tools mentioned that the resume does not contain."""
    return sorted(s for s in set(extract_skills(text)) - GENERIC if s not in resume_skills)

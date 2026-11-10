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


# ── Claim provenance (guard v2) ─────────────────────────────────────────────────────────────────────────────
# Every tailored bullet cites its sources: resume bullets ("exp0.b1", "proj2.b0", "add1") and/or proof items
# ("proof.gh.<repo>" for a verified GitHub repo, "proof.item.<id>" for a linked project or certificate). A bullet
# with no valid source, or with a skill, tool or number its sources don't contain, is reverted and logged.


def proof_contexts(evidence: dict | None) -> dict[str, str]:
    """source_id -> text for the proof items a bullet may cite. Only ownership-verified GitHub repos count."""
    ev = evidence or {}
    ctx: dict[str, str] = {}
    gh = ev.get("github") or {}
    if gh.get("verified"):
        for r in gh.get("top_repos", []):
            name = r.get("name") or ""
            if name:
                ctx[f"proof.gh.{name}"] = f"{name} {r.get('language') or ''} {r.get('description') or ''} {' '.join(r.get('topics', []))}"
    for it in ev.get("items", []):
        if it.get("id") and it.get("live") is not False:
            ctx[f"proof.item.{it['id']}"] = f"{it.get('kind', '')} {it.get('title', '')}"
    return ctx


def source_label(source_id: str, resume: ResumeData, proofs: dict[str, str]) -> str:
    """A human label for the source chip in the review queue."""
    import re as _re

    if source_id.startswith("proof.gh."):
        return f"GitHub · {source_id.removeprefix('proof.gh.')}"
    if source_id.startswith("proof.item."):
        return "Proof · " + proofs.get(source_id, "linked item").split(" ", 1)[-1][:60]
    m = _re.fullmatch(r"(exp|proj)(\d+)\.b(\d+)", source_id)
    if m:
        kind, i, j = m.group(1), int(m.group(2)), int(m.group(3))
        if kind == "exp" and i < len(resume.experience):
            return f"Resume · {resume.experience[i].title or resume.experience[i].organization} · line {j + 1}"
        if kind == "proj" and i < len(resume.projects):
            return f"Resume · {resume.projects[i].name} · line {j + 1}"
    m = _re.fullmatch(r"add(\d+)", source_id)
    if m and int(m.group(1)) < len(resume.additional):
        return f"Skill check · {resume.additional[int(m.group(1))].skill}"
    return "Resume"


@dataclass
class ClaimVerdict:
    ok: bool
    reason: str = ""
    fabricated: list[str] = field(default_factory=list)
    misattributed: list[str] = field(default_factory=list)
    numbers: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)  # the valid refs

    def as_dict(self) -> dict:
        return {"reason": self.reason, "fabricated": self.fabricated, "misattributed": self.misattributed, "numbers": self.numbers}


def check_claim(rewritten: str, refs: list[str], contexts: dict[str, str], allowed_skills: set[str]) -> ClaimVerdict:
    """contexts: every citable source (resume bullets + proof items). allowed_skills: the resume's skills plus the
    skills proof items demonstrate."""
    valid = [r for r in dict.fromkeys(refs) if r in contexts]
    if not valid:
        return ClaimVerdict(False, "No source: the bullet doesn't cite a line of your resume or a proof item")
    cited = "\n".join(contexts[r] for r in valid)
    # A resume bullet's own line holds its numbers; the role/project header line doesn't count for figures.
    cited_lines = "\n".join(contexts[r].split("\n", 1)[-1] for r in valid)
    used = set(extract_skills(rewritten)) - GENERIC
    in_sources = set(extract_skills(cited))
    fabricated = sorted(s for s in used if s not in allowed_skills and s not in in_sources)
    misattributed = sorted(s for s in used if s not in fabricated and s not in in_sources)
    numbers = sorted(_numbers(rewritten) - _numbers(cited_lines))
    reasons = []
    if fabricated:
        reasons.append(f"adds {', '.join(fabricated)}, which isn't in your resume or proof")
    if misattributed:
        reasons.append(f"moves {', '.join(misattributed)} from elsewhere into this line")
    if numbers:
        reasons.append(f"adds the figure {', '.join(numbers)}, which isn't in the source")
    return ClaimVerdict(not reasons, "; ".join(reasons).capitalize(), fabricated, misattributed, numbers, valid)

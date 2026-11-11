"""One-click resume improvement: applies the ATS report's fixes to the resume itself, without inventing anything.

What it changes:
- Weak bullets are rewritten (strong verb first, filler cut, one line). Each rewrite keeps every fact and number of its
  own bullet; the no-fabrication guard reverts any rewrite that adds a skill, tool or figure. No [placeholders] are
  written into a resume meant for download: a bullet without a result keeps its facts and the report still says to
  add one.
- Missing keywords are added to Skills only when the student confirms they have used them (ticked in the UI).
- The summary is written (or tightened to 25-70 words) from the resume's own facts: degree, strongest skills,
  projects and the target field.
- Skills are ordered with the job's (or the field's) keywords first.
The AI does this when available; without it, rule-based rewrites and a template summary do the same job, more simply.
"""

import re

from pydantic import BaseModel, Field

from app.agents.guard import check_claim, check_freeform
from app.ats_lexicon import ACTION_VERBS, INDUSTRIES, WEAK_PHRASES
from app.llm import CallContext, LLMOutputError, LLMUnavailable, get_llm
from app.schemas import ResumeData
from app.services import ats
from app.skills import canonicalize, extract_skills

# Weak lead-ins and the verb to use when no "-ing" verb follows them.
WEAK_LEADS = [
    (r"^(was )?responsible for\s+", "Owned"),
    (r"^worked on\s+", "Developed"),
    (r"^(helped|assisted)( in| with)?\s+", "Supported"),
    (r"^(was )?involved in\s+", "Contributed to"),
    (r"^participated in\s+", "Took part in"),
    (r"^handled\s+", "Managed"),
    (r"^tasked with\s+", "Delivered"),
    (r"^in charge of\s+", "Led"),
    (r"^duties included\s+", "Handled"),
]
GERUND_TO_PAST = {
    "making": "Built", "building": "Built", "developing": "Developed", "creating": "Created", "designing": "Designed",
    "managing": "Managed", "leading": "Led", "analysing": "Analysed", "analyzing": "Analyzed", "implementing": "Implemented",
    "writing": "Wrote", "testing": "Tested", "organising": "Organised", "organizing": "Organized", "coordinating": "Coordinated",
    "preparing": "Prepared", "conducting": "Conducted", "maintaining": "Maintained", "supporting": "Supported",
    "improving": "Improved", "handling": "Managed", "planning": "Planned", "researching": "Researched", "teaching": "Taught",
    "training": "Trained", "deploying": "Deployed", "automating": "Automated", "reviewing": "Reviewed", "running": "Ran",
    "setting up": "Set up", "collecting": "Collected", "cleaning": "Cleaned", "presenting": "Presented", "selling": "Sold",
}
GERUND = re.compile(r"^(" + "|".join(sorted(GERUND_TO_PAST, key=len, reverse=True)) + r")\b", re.I)


def rule_rewrite(text: str) -> str:
    """Strong past-tense opener, no filler, sentence case. Keeps every fact (only the opening words change)."""
    t = text.strip().rstrip(".")
    fallback = None
    for pat, verb in WEAK_LEADS:
        m = re.match(pat, t, flags=re.I)
        if m:
            t, fallback = t[m.end() :], verb
            break
    m = GERUND.match(t)
    if m:
        t = GERUND_TO_PAST[m.group(1).lower()] + t[m.end() :]
    elif fallback:
        t = f"{fallback} {t}"
    t = re.sub(r"(,)?\s+(etc\.?|and so on)$", "", t, flags=re.I)
    return t[:1].upper() + t[1:]


class BulletFixes(BaseModel):
    bullets: list[str] = Field(description="The rewritten bullets, same order and count as given")


class Summary(BaseModel):
    summary: str = Field(description="2-3 sentences, 30-60 words")


BULLET_SYSTEM = """You improve resume bullets for applicant tracking systems and recruiters. For EACH bullet:
- Keep every fact and number exactly. Never add a tool, skill, number, team size, outcome or responsibility.
- Start with a strong past-tense action verb; cut filler ("responsible for", "worked on", "helped", "various", "etc").
- One line, under 28 words. No first person. No placeholders or brackets.
- You may use the target job's wording for things the bullet already shows.
Return the bullets in the same order and the same count."""

SUMMARY_SYSTEM = """Write a resume summary for a student applying to internships or entry-level roles: 2-3 sentences, 30-60
words, no first person, no clichés (hardworking, passionate, team player). Use ONLY the facts provided: degree, college,
skills, projects and experience. Name the target field. Never invent results, numbers, tools or experience."""


def template_summary(resume: ResumeData, industry: str, top_skills: list[str]) -> str:
    edu = resume.education[0] if resume.education else None
    who = f"{edu.degree} student at {edu.school}" if edu and edu.degree and edu.school else f"{edu.degree or edu.school} student" if edu else "Student"
    work = [p.name for p in resume.projects if p.name][:2]
    exp = [" at ".join(x for x in (e.title, e.organization) if x) for e in resume.experience if e.title or e.organization][:1]
    parts = [f"{who} with hands-on experience in {', '.join(top_skills[:4])}." if top_skills else f"{who}."]
    if exp and work:
        parts.append(f"Experience as {exp[0]}, and projects such as {' and '.join(work)}.")
    elif exp:
        parts.append(f"Experience as {exp[0]}.")
    elif work:
        parts.append(f"Built projects such as {' and '.join(work)}.")
    parts.append(f"Seeking {INDUSTRIES[industry].name.lower()} internship and entry-level roles.")
    return " ".join(parts)


async def improve(resume: ResumeData, industry_key: str | None, job_title: str, job_description: str, confirmed: list[str], user_id, raw_text: str | None = None, filename: str | None = None) -> dict:
    before = ats.score(ats.view_from_resume(resume, raw_text, filename), industry_key, job_title, job_description)
    industry = before["industry"]
    new = resume.model_copy(deep=True)
    changes: list[dict] = []
    ai_used = False

    # 1) Confirmed keywords join Skills (the student vouched for them), then skills are ordered by what's searched for.
    known = {s.lower() for s in new.skills}
    missing_terms = {m["term"].lower(): m["term"] for m in before["keywords"]["missing"]}
    for k in confirmed:
        term = missing_terms.get(k.lower()) or canonicalize(k)
        if term and term.lower() not in known:
            new.skills.append(term)
            known.add(term.lower())
            changes.append({"section": "Skills", "before": "", "after": term, "why": "You confirmed you've used it, and the job (or field) searches for it."})
    wanted = [m["term"].lower() for m in before["keywords"]["matched"]] + [missing_terms.get(k.lower(), k).lower() for k in confirmed]
    ordered = sorted(new.skills, key=lambda s: (wanted.index(s.lower()) if s.lower() in wanted else len(wanted)))
    if ordered != new.skills:
        new.skills = ordered
        changes.append({"section": "Skills", "before": "", "after": ", ".join(ordered[:6]) + "…", "why": "The skills recruiters search for now come first."})

    # 2) Weak bullets: rewritten, each checked against its own source line.
    weak_ids = [b["id"] for b in before["weak_bullets"] if any(i.startswith(("weak", "doesn't")) for i in b["issues"]) or "too long" in b["issues"]]
    index = dict(new.bullet_index())
    targets = [(sid, index[sid]) for sid in weak_ids if sid in index][:12]
    rewrites: dict[str, str] = {}
    if targets:
        try:
            out = await get_llm().structured(
                agent="tailor",
                tier="smart",
                schema=BulletFixes,
                ctx=CallContext(user_id=user_id),
                max_tokens=1500,
                system=BULLET_SYSTEM,
                prompt=("Target: " + (job_title or INDUSTRIES[industry].name) + "\n" + (job_description[:1500] + "\n" if job_description else "")) + "\n".join(f"{i + 1}. {t}" for i, (_, t) in enumerate(targets)),
            )
            if len(out.bullets) == len(targets):
                ai_used = True
                for (sid, src), rw in zip(targets, out.bullets):
                    rw = re.sub(r"^\s*\d+[.)]\s*", "", rw).strip()
                    if rw and "[" not in rw and check_claim(rw, [sid], {sid: src}, set(extract_skills(src))).ok:
                        rewrites[sid] = rw
        except (LLMUnavailable, LLMOutputError):
            pass
        for sid, src in targets:
            if sid not in rewrites:
                rw = rule_rewrite(src)
                if rw != src.strip().rstrip("."):
                    rewrites[sid] = rw
    for sid, rw in rewrites.items():
        m = re.match(r"(exp|proj)(\d+)\.b(\d+)$", sid)
        if m:
            kind, i, j = m.group(1), int(m.group(2)), int(m.group(3))
            items = new.experience if kind == "exp" else new.projects
            old = items[i].bullets[j]
            items[i].bullets[j] = rw
            changes.append({"section": "Experience" if kind == "exp" else "Projects", "before": old, "after": rw, "why": "Stronger opening verb and no filler; every fact kept."})

    # 3) Summary: written from the resume's own facts when missing or the wrong length.
    words = len(new.summary.split())
    if not new.summary.strip() or not 20 <= words <= 90:
        top = [s for s in new.skills if not s.lower() in ("communication", "teamwork")][:6]
        allowed = {s for s in new.skills} | set(extract_skills(new.embedding_text()))
        summary = ""
        try:
            facts = (
                f"Target field: {INDUSTRIES[industry].name}" + (f" ({job_title})" if job_title else "") + "\n"
                f"Education: {'; '.join(f'{e.degree} {e.school} {e.details}'.strip() for e in new.education) or 'n/a'}\n"
                f"Skills: {', '.join(top)}\nExperience: {'; '.join(f'{e.title} at {e.organization}' for e in new.experience) or 'none'}\n"
                f"Projects: {'; '.join(p.name for p in new.projects) or 'none'}\nCurrent summary: {new.summary or '(none)'}"
            )
            res = await get_llm().structured(agent="tailor", tier="fast", schema=Summary, ctx=CallContext(user_id=user_id), max_tokens=400, system=SUMMARY_SYSTEM, prompt=facts)
            if not check_freeform(res.summary, allowed) and 15 <= len(res.summary.split()) <= 90 and "[" not in res.summary:
                summary, ai_used = res.summary.strip(), True
        except (LLMUnavailable, LLMOutputError):
            pass
        summary = summary or template_summary(new, industry, top)
        changes.append({"section": "Summary", "before": new.summary, "after": summary, "why": "Recruiters skim the summary first; this one names your field and strongest skills, from your own resume."})
        new.summary = summary

    after = ats.score(ats.view_from_resume(new), industry, job_title, job_description)
    still = [m["term"] for m in after["keywords"]["missing"] if not m["soft"]][:10]
    return {
        "resume": new.model_dump(),
        "changes": changes,
        "before": before["score"],
        "after": after["score"],
        "after_report": after,
        "still_missing": still,
        "ai": ai_used,
        "note": "Bullets without a measurable result kept their facts: add your real numbers in the builder for the biggest gain." if any("no measurable result" in b["issues"] for b in before["weak_bullets"]) else "",
    }


__all__ = ["improve", "rule_rewrite", "ACTION_VERBS", "WEAK_PHRASES"]

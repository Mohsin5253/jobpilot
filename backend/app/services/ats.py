"""ATS scoring: how an applicant tracking system and the recruiter searching it will see a resume.

Real ATSs (Workday, Taleo, Greenhouse, Lever, Darwinbox...) do two things that decide whether a human ever reads
a resume: they parse it into fields (so layout, headings and contact details must survive parsing) and they let
recruiters filter and rank candidates by keywords from the job. This module models both, per industry:

- Keywords (the biggest part): with a job description, its terms are weighted by how often and where they appear
  (title and "requirements" lines count more, "nice to have" less). Without one, the field's core search terms are
  used. A keyword used in a bullet counts more than one only listed under Skills, as in recruiter search.
- Impact: bullets that open with an action verb and show a measurable result.
- Format: what breaks parsing (scanned PDFs, columns, icons), contact details, length, pronouns, dates.
- Sections: what recruiters in that field expect (a portfolio for design, certifications for finance...).

Everything is deterministic and explained: each point lost maps to a check with the fix, so the same resume
always gets the same score and the student can see exactly why. No vendor publishes its ranking formula, so this
is a faithful model of how they work, not a copy of any one of them; we never claim otherwise.
"""

import re
from dataclasses import dataclass, field
from functools import lru_cache

from app.ats_lexicon import ACTION_VERBS, CLICHES, DEFAULT_INDUSTRY, FUNDAMENTALS, INDUSTRIES, ROLE_TRACKS, SOFT_SKILLS, WEAK_PHRASES, Industry
from app.schemas import ResumeData
from app.skills import _BOUNDARY_L, _BOUNDARY_R, SKILLS, _patterns, role_digest

# ---------------------------------------------------------------- term matching


@lru_cache
def _term_patterns(industry_key: str) -> tuple[tuple[str, re.Pattern[str], bool], ...]:
    """(canonical, pattern, is_soft) for the industry's own terms and the soft skills."""
    ind = INDUSTRIES[industry_key]
    out = []
    for canon, aliases in ind.terms.items():
        for a in sorted({canon.lower(), *aliases}, key=len, reverse=True):
            out.append((canon, re.compile(_BOUNDARY_L + re.escape(a) + r"(?:s|es)?" + _BOUNDARY_R, re.IGNORECASE), False))
    for canon, aliases in SOFT_SKILLS.items():
        for a in sorted({canon.lower(), *aliases}, key=len, reverse=True):
            out.append((canon, re.compile(_BOUNDARY_L + re.escape(a) + _BOUNDARY_R, re.IGNORECASE), True))
    return tuple(out)


_SLASH = re.compile(r"(?<=[A-Za-z]{3})/(?=[A-Za-z]{3})")


def normalize(text: str) -> str:
    """"Tableau/Power BI" lists two tools; the shared lexicon ignores words glued to a slash (paths, URLs), so
    split word/word pairs. Short pairs like CI/CD, UI/UX and A/B are one term and stay as they are."""
    return _SLASH.sub(" / ", text or "")


def count_terms(text: str, industry_key: str, all_tech: bool = False) -> dict[str, int]:
    """How often each term appears. Tech terms come from the shared lexicon (only this industry's, unless
    all_tech: a job description may ask for any tool)."""
    if not text:
        return {}
    text = normalize(text)
    allowed = None if all_tech else set(INDUSTRIES[industry_key].tech)
    counts: dict[str, int] = {}
    seen_spans: dict[str, set[int]] = {}
    for canon, pat in _patterns():
        if allowed is not None and canon not in allowed:
            continue
        for m in pat.finditer(text):
            spans = seen_spans.setdefault(canon, set())
            if m.start() not in spans:
                spans.add(m.start())
                counts[canon] = counts.get(canon, 0) + 1
    for canon, pat, _ in _term_patterns(industry_key):
        for m in pat.finditer(text):
            spans = seen_spans.setdefault(canon, set())
            if m.start() not in spans:
                spans.add(m.start())
                counts[canon] = counts.get(canon, 0) + 1
    return counts


def _is_soft(term: str) -> bool:
    return term in SOFT_SKILLS


# ---------------------------------------------------------------- the resume, as an ATS sees it


@dataclass
class ResumeView:
    text: str  # everything a parser would index
    narrative: str  # summary + bullets: where a keyword shows it was used, not just listed
    skills: list[str]
    bullets: list[tuple[str, str]]  # (id, text)
    has_summary: bool
    summary_words: int
    experience: int
    projects: int
    education: int
    exp_missing_dates: int
    email: str
    phone: str
    links: list[str]
    raw_text: str | None = None  # the uploaded file's text, for parse checks; None for the builder's own template
    filename: str | None = None
    headings: list[str] = field(default_factory=list)


def view_from_resume(resume: ResumeData, raw_text: str | None = None, filename: str | None = None) -> ResumeView:
    bullets = [(sid, t) for sid, t in resume.bullet_index() if t.strip()]
    exp_headers = [f"{e.title} {e.organization} {e.location}" + (f" Tech: {', '.join(e.tech)}" if e.tech else "") for e in resume.experience]
    proj_headers = [f"{p.name} {' '.join(p.tech)}" for p in resume.projects]
    edu = [f"{e.degree} {e.school} {e.details}" for e in resume.education]
    narrative = "\n".join([resume.summary, *exp_headers, *proj_headers, *(t for _, t in bullets)])
    groups = [f"{g.name}: {', '.join(g.items)}" for g in resume.skill_groups]
    structured = "\n".join([resume.name, resume.email, resume.phone, resume.location, *resume.links, narrative, "Skills: " + ", ".join(resume.skills), *groups, *edu, *resume.certifications])
    text = structured if not raw_text else f"{raw_text}\n{structured}"
    return ResumeView(
        text=text,
        narrative=narrative,
        skills=list(resume.skills),
        bullets=bullets,
        has_summary=bool(resume.summary.strip()),
        summary_words=len(resume.summary.split()),
        experience=sum(1 for e in resume.experience if e.title or e.organization),
        projects=sum(1 for p in resume.projects if p.name or p.bullets),
        education=sum(1 for e in resume.education if e.school or e.degree),
        exp_missing_dates=sum(1 for e in resume.experience if (e.title or e.organization) and not (e.start or e.end)),
        email=resume.email or _first(_EMAIL, raw_text),
        phone=resume.phone or _first(_PHONE, raw_text),
        links=[*resume.links, *_LINK.findall(raw_text or "")],
        raw_text=raw_text,
        filename=filename,
        headings=_headings(raw_text) if raw_text else [],
    )


def view_from_doc(doc, resume: ResumeData) -> ResumeView:
    """The tailored resume (resume_doc.TailoredDoc) exactly as it is sent: our own single-column template."""
    bullets: list[tuple[str, str]] = []
    for kind, sections in doc.body_sections():
        for i, sec in enumerate(sections):
            bullets += [(f"{kind[:4].lower()}{i}.b{j}", b) for j, b in enumerate(sec.bullets) if b.strip()]
    bullets += [(f"add{i}", a) for i, a in enumerate(doc.additional) if a.strip()]
    headers = [f"{s.title_line} {s.meta}" for _, secs in doc.body_sections() for s in secs]
    stacks = [f"Tech: {s.tech}" for _, secs in doc.body_sections() for s in secs if s.tech]
    narrative = "\n".join([doc.summary, *headers, *(t for _, t in bullets), *stacks])
    skills = [*doc.key_skills, *doc.other_skills]
    text = "\n".join([doc.name, doc.contact, narrative, "Skills: " + ", ".join(skills), *doc.education, *doc.certifications])
    return ResumeView(
        text=text,
        narrative=narrative,
        skills=skills,
        bullets=bullets,
        has_summary=bool(doc.summary.strip()),
        summary_words=len(doc.summary.split()),
        experience=len(doc.experience),
        projects=len(doc.projects),
        education=len(doc.education),
        exp_missing_dates=sum(1 for s in doc.experience if not s.meta),
        email=resume.email,
        phone=resume.phone,
        links=list(resume.links),
    )


_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE = re.compile(r"(?:\+?\d{1,3}[\s-]?)?(?:\d[\s-]?){9,11}\d")
_LINK = re.compile(r"(?:https?://)?(?:www\.)?(?:[a-z0-9-]+\.)+(?:com|in|io|dev|me|net|org|app|site|website|co)(?:/[^\s|,)]*)?", re.IGNORECASE)
_PRONOUN = re.compile(r"\b(I|me|my|myself)\b")
_NUMBER = re.compile(r"(\d|₹|\$|%|\bone\b|\btwo\b|\bthree\b|\bfive\b|\bten\b|\bhundred|\bthousand|\blakh|\bcrore|\bdoubled\b|\btripled\b|\bhalved\b)", re.IGNORECASE)
_PRIVATE_USE = re.compile(r"[-\U000f0000-\U000fffff]")
_DECOR = re.compile(r"[★☆✓✔✗✘●◆◇■□▪▫►▶➤➔→⚫⚪❖✦✧]")
_STD_HEADINGS = {
    "summary": r"(professional\s+)?summary|profile|objective|about me",
    "skills": r"(technical\s+|key\s+|core\s+)?skills|technologies|tech stack|tools",
    "experience": r"(work\s+|professional\s+)?experience|internships?|employment|work history",
    "projects": r"(academic\s+|personal\s+|key\s+)?projects",
    "education": r"education|academics|academic (details|qualifications)|qualifications",
    "certifications": r"certifications?|courses|licen[cs]es",
    "achievements": r"achievements|awards|honou?rs|accomplishments|extra[- ]?curricular|activities|positions of responsibility|leadership",
}
_HEADING_RE = {k: re.compile(rf"^\s*(?:{v})\s*:?\s*$", re.IGNORECASE) for k, v in _STD_HEADINGS.items()}


def _first(pat: re.Pattern[str], text: str | None) -> str:
    m = pat.search(text or "")
    return m.group(0) if m else ""


def _headings(raw: str) -> list[str]:
    found = []
    for line in raw.splitlines():
        line = line.strip()
        if 2 < len(line) < 45:
            for k, rx in _HEADING_RE.items():
                if rx.match(line) and k not in found:
                    found.append(k)
    return found


def resume_text(resume: ResumeData) -> str:
    return view_from_resume(resume).text


# ---------------------------------------------------------------- industry detection


def detect_industry(title: str = "", description: str = "", fallback_text: str = "") -> tuple[str, float]:
    """(industry key, confidence 0-1). The job title decides when it names a field; otherwise the keywords do."""
    t = f" {title.lower()} "
    # The most specific title phrase wins: "Business Development Associate" is sales (not the generic "associate"),
    # "Data Analyst" is analytics, "ML Engineer" is data science even though it says "engineer".
    best_key, best_len = None, 0
    for key, ind in INDUSTRIES.items():
        for w in ind.title_words:
            if w in t and len(w.strip()) > best_len:
                best_key, best_len = key, len(w.strip())
    if best_key:
        return best_key, 0.9
    text = f"{title}\n{description}" if description.strip() else fallback_text
    if not text.strip():
        return DEFAULT_INDUSTRY, 0.0
    scores = {}
    for key, ind in INDUSTRIES.items():
        counts = count_terms(text, key)
        hits = sum(min(c, 3) for term, c in counts.items() if not _is_soft(term))
        scores[key] = hits / (len(ind.tech) + len(ind.terms)) ** 0.5
    best = max(scores, key=scores.get)
    total = sum(scores.values()) or 1
    return (best if scores[best] > 0 else DEFAULT_INDUSTRY), round(scores[best] / total, 2)


# ---------------------------------------------------------------- keywords


@dataclass
class Keyword:
    term: str
    weight: float
    importance: str  # required | preferred | core | nice
    mentions: int = 1
    soft: bool = False
    # Terms the job accepts instead ("FastAPI or Django"): having any one of them satisfies this keyword.
    alternatives: set[str] = field(default_factory=set)


def term_spans(text: str, industry_key: str) -> list[tuple[str, int, int]]:
    """(term, start, end) for every term in text (normalised), longest match first at each position."""
    text = normalize(text)
    spans: list[tuple[str, int, int]] = []
    for canon, pat in _patterns():
        spans += [(canon, m.start(), m.end()) for m in pat.finditer(text)]
    for canon, pat, _ in _term_patterns(industry_key):
        spans += [(canon, m.start(), m.end()) for m in pat.finditer(text)]
    spans.sort(key=lambda s: (s[1], -(s[2] - s[1])))
    out, last_end = [], -1
    for s in spans:
        if s[1] >= last_end:
            out.append(s)
            last_end = s[2]
    return out


_OR_GAP = re.compile(r"^\s*(?:,|/|or|,\s*or|and/or|\|)\s*$", re.IGNORECASE)


def alternative_groups(line: str, industry_key: str) -> list[set[str]]:
    """Terms the line offers as alternatives: "FastAPI or Django", "Tableau/Power BI", "Java, C++ or Go"."""
    if not re.search(r"\bor\b|/", line, re.IGNORECASE):
        return []
    line = normalize(line)
    spans = term_spans(line, industry_key)
    groups: list[set[str]] = []
    cur: list[tuple[str, int, int]] = []
    for s in spans:
        if cur and _OR_GAP.match(line[cur[-1][2] : s[1]]):
            cur.append(s)
        else:
            if len(cur) > 1:
                groups.append(cur)
            cur = [s]
    if len(cur) > 1:
        groups.append(cur)
    out = []
    for g in groups:
        between = line[g[0][1] : g[-1][2]]
        if re.search(r"\bor\b|/", between, re.IGNORECASE) and not re.search(r"\band\b(?!/)", between, re.IGNORECASE):
            out.append({t for t, _, _ in g})
    return out


_REQUIRED_LINE = re.compile(r"\b(require|must|mandatory|essential|minimum|need|should have|proficien|strong|solid|expert|hands-on)", re.IGNORECASE)
_PREFERRED_LINE = re.compile(r"\b(prefer|nice to have|good to have|bonus|plus|desirable|familiarity|exposure|optional|advantage)", re.IGNORECASE)


def jd_keywords(title: str, description: str, industry_key: str) -> list[Keyword]:
    """The job's search terms, weighted the way a recruiter would filter: the title's terms first, then terms in
    requirement lines and terms repeated across the posting; "nice to have" terms count less."""
    digest = role_digest(description or "", 8000) or (description or "")
    terms: dict[str, Keyword] = {}
    for line in [title, *digest.splitlines()]:
        counts = count_terms(line, industry_key, all_tech=True)
        if not counts:
            continue
        if line is title:
            factor, imp = 1.6, "required"
        elif _PREFERRED_LINE.search(line):
            factor, imp = 0.65, "preferred"
        elif _REQUIRED_LINE.search(line):
            factor, imp = 1.3, "required"
        else:
            factor, imp = 1.0, "core"
        groups = alternative_groups(line, industry_key)
        for term, c in counts.items():
            soft = _is_soft(term)
            k = terms.get(term)
            alts = set().union(*(g for g in groups if term in g)) - {term} if groups else set()
            if k is None:
                terms[term] = Keyword(term, factor * (0.35 if soft else 1.0), imp, c, soft, alts)
            else:
                k.alternatives |= alts
                k.mentions += c
                k.weight = max(k.weight, factor * (0.35 if soft else 1.0))
                if imp == "required" or (imp == "core" and k.importance == "preferred"):
                    k.importance = imp
    for k in terms.values():
        k.weight = round(k.weight * min(1 + 0.25 * (k.mentions - 1), 1.75), 3)
    return sorted(terms.values(), key=lambda k: (-k.weight, k.term))[:30]


def _recognizable(industry_key: str, term: str) -> bool:
    from app.skills import SKILLS

    return term in SKILLS or term in INDUSTRIES[industry_key].tech or term in INDUSTRIES[industry_key].terms


def detect_track(industry_key: str, v: "ResumeView") -> str | None:
    """The role this resume fits best within its field: the track whose keywords it shows most, nudged by the
    role words in its summary, titles and project names."""
    tracks = ROLE_TRACKS.get(industry_key)
    if not tracks:
        return None
    counts = count_terms(v.text, industry_key, all_tech=True)
    head = (v.narrative or "")[:1500].lower()
    best, best_score = None, -1.0
    for key, (_, words, kws) in tracks.items():
        kws = [k for k in kws if _recognizable(industry_key, k)]
        cover = sum(1 for k in kws if counts.get(k)) / max(1, len(kws))
        bonus = min(0.3, 0.15 * sum(1 for w in words if w in head))
        if cover + bonus > best_score:
            best, best_score = key, cover + bonus
    return best


def industry_keywords(industry_key: str, track: str | None = None) -> list[Keyword]:
    if track and track in ROLE_TRACKS.get(industry_key, {}):
        out: list[Keyword] = []
        seen: set[str] = set()
        for term in FUNDAMENTALS.get(industry_key, ()):
            if _recognizable(industry_key, term) and term not in seen:
                out.append(Keyword(term, 1.0, "core"))
                seen.add(term)
        track_terms = [t for t in ROLE_TRACKS[industry_key][track][2] if _recognizable(industry_key, t) and t not in seen]
        for i, term in enumerate(track_terms):
            out.append(Keyword(term, 1.0 if i < 7 else 0.4, "core" if i < 7 else "nice"))
        return out
    ind = INDUSTRIES[industry_key]
    ordered = [*ind.tech, *ind.terms]
    out = []
    for i, term in enumerate(ordered[: ind.core + 10]):
        core = i < ind.core
        out.append(Keyword(term, 1.0 if core else 0.4, "core" if core else "nice"))
    return out


# ---------------------------------------------------------------- checks


@dataclass
class Check:
    id: str
    category: str  # format | sections
    label: str
    status: str  # pass | warn | fail
    detail: str
    fix: str = ""
    weight: float = 1.0

    @property
    def value(self) -> float:
        return {"pass": 1.0, "warn": 0.5, "fail": 0.0}[self.status]


def _word_count(v: ResumeView) -> int:
    return len((v.raw_text or v.text).split())


def format_checks(v: ResumeView, ind: Industry) -> list[Check]:
    c: list[Check] = []
    raw = v.raw_text
    if raw is None:
        # Built by JobPilot (the builder's draft or a tailored resume): our single-column template with standard
        # headings, real text and no icons, exported as PDF/DOCX. It passes the parse checks by construction.
        made = "Generated with JobPilot's ATS-safe template."
        c += [
            Check("parse", "format", "Text can be read by an ATS", "pass", made, weight=3),
            Check("symbols", "format", "No icons or decorative symbols", "pass", made, weight=1),
            Check("columns", "format", "Single-column layout", "pass", made, weight=2),
            Check("headings", "format", "Standard section headings", "pass", made, weight=2),
            Check("filetype", "format", "ATS-safe file type", "pass", "Exported as PDF or DOCX.", weight=1),
        ]
    else:
        n = len(raw.strip())
        if n < 300:
            c.append(Check("parse", "format", "Text can be read by an ATS", "fail", f"Only {n} characters of text could be read from your file. It is probably a scanned image or built from graphics, so an ATS sees an almost empty resume.", "Export it from Word or Google Docs as a text PDF (not a photo or a design tool export), or rebuild it in the Resume builder.", 3))
        else:
            c.append(Check("parse", "format", "Text can be read by an ATS", "pass", "Your file's text was read cleanly.", weight=3))
        icons = len(_PRIVATE_USE.findall(raw)) + len(_DECOR.findall(raw))
        c.append(
            Check("symbols", "format", "No icons or decorative symbols", "warn", f"{icons} icon or symbol characters found. Parsers turn these into junk characters, and icons used instead of words (a phone icon instead of 'Phone') are lost.", "Replace icons with plain words and use simple round bullets.", 1)
            if icons > 3
            else Check("symbols", "format", "No icons or decorative symbols", "pass", "No problem symbols found.", weight=1)
        )
        lines = [ln for ln in raw.splitlines() if ln.strip()]
        gappy = sum(1 for ln in lines if len(re.findall(r"\S(?: {4,}|\t+)\S", ln)) >= 1)
        c.append(
            Check("columns", "format", "Single-column layout", "warn", f"{gappy} of {len(lines)} lines look like side-by-side columns or a table. Many ATSs read straight across columns and scramble the text.", "Use one column; put skills and contact details in their own sections, not a sidebar.", 2)
            if lines and gappy / len(lines) > 0.15
            else Check("columns", "format", "Single-column layout", "pass", "Reads top to bottom in one column.", weight=2)
        )
        found = set(v.headings)
        std_ok = {"skills", "education"} <= found and bool({"experience", "projects"} & found)
        c.append(
            Check("headings", "format", "Standard section headings", "pass", f"Found: {', '.join(sorted(found))}.", weight=2)
            if std_ok
            else Check("headings", "format", "Standard section headings", "warn", "Some sections don't use headings an ATS recognises" + (f" (found only: {', '.join(sorted(found))})" if found else "") + ".", "Use plain headings: Summary, Skills, Experience (or Internships), Projects, Education, Certifications.", 2)
        )
    if v.filename:
        ext = v.filename.rsplit(".", 1)[-1].lower() if "." in v.filename else ""
        if ext in ("pdf", "docx"):
            c.append(Check("filetype", "format", "ATS-safe file type", "pass", f".{ext} is read by every major ATS.", weight=1))
        else:
            c.append(Check("filetype", "format", "ATS-safe file type", "warn", f".{ext or 'unknown'} files are not read reliably.", "Upload a .pdf or .docx.", 1))
    c.append(Check("email", "format", "Email address", "pass" if v.email else "fail", v.email and "Present." or "No email address found.", "Add a professional email (firstname.lastname@...).", 2))
    c.append(Check("phone", "format", "Phone number", "pass" if v.phone else "fail", "Present." if v.phone else "No phone number found.", "Add a 10-digit mobile number with +91.", 1.5))
    has_li = any("linkedin.com" in link.lower() for link in v.links) or "linkedin.com" in v.text.lower()
    c.append(Check("linkedin", "format", "LinkedIn profile URL", "pass" if has_li else "warn", "Present." if has_li else "Recruiters look you up on LinkedIn; there's no profile link.", "Add your linkedin.com/in/ URL to the contact line.", 1))
    words = _word_count(v)
    if words < 220:
        c.append(Check("length", "format", "Length", "warn", f"About {words} words: too thin to rank for many searches.", "Add projects, coursework and achievements with what you did and the result.", 1.5))
    elif words > 950:
        c.append(Check("length", "format", "Length", "warn", f"About {words} words: likely 2+ pages. For internships and fresher roles recruiters expect one page.", "Cut older or unrelated items and keep bullets to one line.", 1.5))
    else:
        c.append(Check("length", "format", "Length", "pass", f"About {words} words, a good one-page length.", weight=1.5))
    long_b = [t for _, t in v.bullets if len(t.split()) > 35]
    short_b = [t for _, t in v.bullets if len(t.split()) < 6]
    if v.bullets and (len(long_b) + len(short_b)) / len(v.bullets) > 0.3:
        c.append(Check("bullet_length", "format", "Bullet length", "warn", f"{len(long_b)} bullet(s) are over 35 words and {len(short_b)} under 6.", "Aim for one line each (12-30 words): what you did, how, and the result.", 1))
    else:
        c.append(Check("bullet_length", "format", "Bullet length", "pass", "Bullets are a readable length.", weight=1))
    pron = len(_PRONOUN.findall(v.narrative))
    c.append(
        Check("pronouns", "format", "No first-person pronouns", "warn", f"'I', 'me' or 'my' appears {pron} times.", "Drop the pronoun: 'Built…' instead of 'I built…'.", 0.5)
        if pron > 1
        else Check("pronouns", "format", "No first-person pronouns", "pass", "Written in resume style.", weight=0.5)
    )
    if v.experience:
        c.append(
            Check("dates", "format", "Dates on every role", "warn", f"{v.exp_missing_dates} role(s) have no dates. ATSs compute experience from dates.", "Add month and year for start and end (e.g. Jun 2025 – Aug 2025).", 1)
            if v.exp_missing_dates
            else Check("dates", "format", "Dates on every role", "pass", "Every role is dated.", weight=1)
        )
    return c


def section_checks(v: ResumeView, ind: Industry) -> list[Check]:
    c: list[Check] = []
    exp = ind.expects
    if "summary" in exp or v.has_summary:
        if not v.has_summary:
            c.append(Check("summary", "sections", "Summary", "warn" if "summary" in exp else "pass", f"No summary. In {ind.name}, recruiters skim a 2-3 line summary first.", "Add 2-3 lines: who you are, your strongest skills for this field, and what you're looking for.", 1.5))
        elif not 15 <= v.summary_words <= 90:
            c.append(Check("summary", "sections", "Summary", "warn", f"Your summary is {v.summary_words} words.", "Keep it to 25-70 words.", 1.5))
        else:
            c.append(Check("summary", "sections", "Summary", "pass", "A concise summary.", weight=1.5))
    n = len(v.skills)
    c.append(Check("skills", "sections", "Skills section", "pass" if n >= 6 else "warn" if n else "fail", f"{n} skill(s) listed." if n else "No skills section.", "List the tools and skills you have actually used, grouped (Languages, Tools, ...).", 2))
    has_body = v.experience > 0 or v.projects >= 2
    c.append(Check("experience", "sections", "Experience or projects", "pass" if has_body else "warn" if v.projects else "fail", f"{v.experience} role(s), {v.projects} project(s).", "Freshers: list 2-4 projects with bullets (problem, what you built, result). Internships, freelance and college-club work all count.", 3))
    c.append(Check("education", "sections", "Education", "pass" if v.education else "fail", "Present." if v.education else "No education section.", "Add degree, college, years and CGPA/percentage.", 2))
    if "certifications" in exp:
        cert = re.search(r"certif|cfa|nism|frm|acca|cma|ca (inter|final)|nptel|coursera|udemy", v.text, re.IGNORECASE)
        c.append(Check("certifications", "sections", "Certifications", "pass" if cert else "warn", "Present." if cert else f"No certifications. In {ind.name} they are a common shortlisting filter.", "List finished certifications with issuer and year (e.g. NISM Series VIII, NPTEL).", 1.5))
    if ind.proof_links:
        has = any(any(p in link.lower() for p in ind.proof_links) for link in v.links) or any(p in v.text.lower() for p in ind.proof_links)
        c.append(Check("proof_link", "sections", "Proof of work link", "pass" if has else ("fail" if ind.key == "design" else "warn"), "Present." if has else f"No link to {ind.proof_label}.", f"Add {ind.proof_label} to your contact line.", 2.5 if ind.key == "design" else 1.5))
    cliche = [w for w in CLICHES if w in v.text.lower()]
    if cliche:
        c.append(Check("cliches", "sections", "No filler words", "warn", f"Filler phrases: {', '.join(cliche[:4])}.", "Show it instead: a bullet with a result says 'hardworking' better than the word does.", 0.5))
    return c


# ---------------------------------------------------------------- impact


_LEAD = re.compile(r"^[\W\d_]*")


def _first_word(text: str) -> str:
    return _LEAD.sub("", text).split(" ", 1)[0].lower().strip(",.;:")


def bullet_issues(text: str) -> list[str]:
    issues = []
    low = text.lower().strip()
    first = _first_word(text)
    weak = next((w for w in WEAK_PHRASES if low.startswith(w) or f" {w} " in f" {low[:40]} "), None)
    if weak:
        issues.append(f"weak opener ('{weak}')")
    elif first not in ACTION_VERBS:
        issues.append("doesn't start with an action verb")
    if not _NUMBER.search(text):
        issues.append("no measurable result")
    if len(text.split()) > 35:
        issues.append("too long")
    return issues


def bullet_suggestion(text: str, issues: list[str]) -> str:
    """A rule-based fix. It never invents facts: numbers are left as [placeholders] for the student to fill in."""
    tips = []
    if any(i.startswith("weak opener") or i.startswith("doesn't start") for i in issues):
        tips.append("Open with what you did: 'Built…', 'Analysed…', 'Led…', 'Automated…'")
    if "no measurable result" in issues:
        tips.append("add a real result: how many users, how much time or money saved, accuracy, rank (e.g. '…for [N] users' or '…cutting time by [X]%')")
    if "too long" in issues:
        tips.append("cut it to one line")
    if not tips:
        return ""
    text = "; ".join(tips) + "."
    return text[0].upper() + text[1:]


def impact(v: ResumeView) -> tuple[float, dict, list[dict]]:
    if not v.bullets:
        return 0.0, {"bullets": 0, "action_pct": 0, "quantified_pct": 0, "weak": 0}, []
    rows = [(sid, t, bullet_issues(t)) for sid, t in v.bullets]
    action = sum(1 for _, _, iss in rows if not any(i.startswith(("weak", "doesn't")) for i in iss))
    quant = sum(1 for _, _, iss in rows if "no measurable result" not in iss)
    weak = sum(1 for _, _, iss in rows if any(i.startswith("weak") for i in iss))
    n = len(rows)
    a_pct, q_pct = action / n, quant / n
    score = 0.45 * min(1, a_pct / 0.85) + 0.40 * min(1, q_pct / 0.5) + 0.15 * (1 - min(1, weak / 3))
    worst = sorted((r for r in rows if r[2]), key=lambda r: -len(r[2]))[:8]
    weak_bullets = [{"id": sid, "text": t, "issues": iss, "suggestion": bullet_suggestion(t, iss)} for sid, t, iss in worst]
    stats = {"bullets": n, "action_pct": round(100 * a_pct), "quantified_pct": round(100 * q_pct), "weak": weak}
    return score, stats, weak_bullets


# ---------------------------------------------------------------- the score


def _grade(score: int) -> str:
    return "Excellent" if score >= 85 else "Good" if score >= 70 else "Fair" if score >= 55 else "Needs work"


def _weights(ind: Industry, with_jd: bool) -> dict[str, float]:
    kw, im, fm, se = ind.weights
    if with_jd:  # matching one job: keyword fit is what ranks you in that job's applicant list
        kw, im, fm, se = kw + 0.10, im - 0.04, fm - 0.03, se - 0.03
    return {"keywords": kw, "impact": im, "format": fm, "sections": se}


def keyword_match(v: ResumeView, keywords: list[Keyword], industry_key: str, with_jd: bool) -> tuple[float, dict]:
    have_all = count_terms(v.text, industry_key, all_tech=True)
    in_story = count_terms(v.narrative, industry_key, all_tech=True)
    total = sum(k.weight for k in keywords) or 1
    got = 0.0
    matched, missing = [], []
    for k in keywords:
        alt = next((a for a in sorted(k.alternatives) if have_all.get(a)), None) if not have_all.get(k.term) else None
        if have_all.get(k.term) or alt:
            hit = k.term if have_all.get(k.term) else alt
            context = bool(in_story.get(hit))
            got += k.weight * (1.0 if context or k.soft else 0.85)
            matched.append({"term": k.term, "weight": k.weight, "importance": k.importance, "in_context": context, "soft": k.soft, **({"via": alt} if alt else {})})
        else:
            missing.append({"term": k.term, "weight": k.weight, "importance": k.importance, "soft": k.soft})
    coverage = got / total
    target = 0.8 if with_jd else 0.6  # recruiters shortlist around 75-80% of a job's terms; a field's core list is broader
    score = min(1.0, coverage / target)
    return score, {
        "coverage": round(100 * coverage),
        "matched": matched,
        "missing": missing,
        "listed_only": [m["term"] for m in matched if not m["in_context"] and not m["soft"]],
    }


def score(v: ResumeView, industry_key: str | None = None, job_title: str = "", job_description: str = "") -> dict:
    with_jd = bool(job_description.strip() or job_title.strip())
    detected, confidence = detect_industry(job_title, job_description, v.text)
    key = industry_key if industry_key in INDUSTRIES else detected
    ind = INDUSTRIES[key]
    track = None if with_jd else detect_track(key, v)
    keywords = jd_keywords(job_title, job_description, key) if with_jd else industry_keywords(key, track)
    if with_jd and len([k for k in keywords if not k.soft]) < 4:
        # A thin posting: fill in with the field's core terms so the score still means something.
        have = {k.term for k in keywords}
        keywords += [k for k in industry_keywords(key)[: ind.core] if k.term not in have]
    w = _weights(ind, with_jd)

    kw_score, kw = keyword_match(v, keywords, key, with_jd)
    im_score, im_stats, weak_bullets = impact(v)
    fchecks = format_checks(v, ind)
    schecks = section_checks(v, ind)
    f_score = sum(c.weight * c.value for c in fchecks) / (sum(c.weight for c in fchecks) or 1)
    s_score = sum(c.weight * c.value for c in schecks) / (sum(c.weight for c in schecks) or 1)
    # A resume the ATS can't read scores near zero whatever its content: nothing reaches the recruiter's search.
    unreadable = any(c.id == "parse" and c.status == "fail" for c in fchecks)
    parts = {"keywords": kw_score, "impact": im_score, "format": f_score, "sections": s_score}
    total = sum(w[k] * parts[k] for k in parts) * 100
    if unreadable:
        total = min(total, 25)
    total_i = round(total)

    labels = {"keywords": "Keyword match", "impact": "Impact & achievements", "format": "Format & parsing", "sections": "Sections & proof"}
    breakdown = [{"key": k, "label": labels[k], "score": round(parts[k] * 100), "weight": round(w[k] * 100), "points": round(parts[k] * w[k] * 100, 1)} for k in parts]

    improvements = _improvements(v, ind, w, kw, kw_score, keywords, im_stats, fchecks + schecks, with_jd)
    return {
        "score": total_i,
        "grade": _grade(total_i),
        "industry": key,
        "industry_name": ind.name,
        "track": {"key": track, "label": ROLE_TRACKS[key][track][0]} if track else None,
        "detected_industry": detected,
        "detection_confidence": confidence,
        "mode": "job" if with_jd else "industry",
        "breakdown": breakdown,
        "keywords": kw,
        "checks": [c.__dict__ for c in fchecks + schecks],
        "weak_bullets": weak_bullets,
        "stats": {**im_stats, "words": _word_count(v), "skills": len(v.skills)},
        "improvements": improvements,
        "gaps": _gaps(kw, fchecks + schecks, im_stats, ind, with_jd),
    }


def _improvements(v, ind, w, kw, kw_score, keywords, im_stats, checks, with_jd) -> list[dict]:
    """What to fix, biggest score gain first. Gains are what the score would rise by if this alone were fixed."""
    out = []
    missing_hard = [m for m in kw["missing"] if not m["soft"]]
    if missing_hard:
        top = missing_hard[:6]
        total = sum(k.weight for k in keywords) or 1
        target = 0.8 if with_jd else 0.6
        new_cov = (kw["coverage"] / 100) + sum(m["weight"] for m in top) / total
        gain = (min(1, new_cov / target) - kw_score) * w["keywords"] * 100
        out.append({
            "area": "keywords",
            "title": f"Add the missing {'job' if with_jd else ind.name.lower()} keywords you genuinely have",
            "detail": "Missing: " + ", ".join(m["term"] for m in top) + ". Only add a keyword if you have used it, and show it in a project or experience bullet, not just in Skills. Anything you can't back up will surface in the interview.",
            "gain": max(1, round(gain)),
        })
    if kw["listed_only"]:
        out.append({
            "area": "keywords",
            "title": "Show your listed skills in action",
            "detail": f"{', '.join(kw['listed_only'][:6])} appear only in your Skills list. Recruiters and ATS ranking trust a skill more when a bullet shows where you used it.",
            "gain": max(1, round(0.15 * len(kw["listed_only"][:6]) / max(len(keywords), 1) * w["keywords"] * 100)),
        })
    if im_stats.get("bullets"):
        n = im_stats["bullets"]
        unquant = round(n * (100 - im_stats["quantified_pct"]) / 100)
        if im_stats["quantified_pct"] < 50:
            gain = 0.40 * (1 - min(1, im_stats["quantified_pct"] / 50)) * w["impact"] * 100
            out.append({"area": "impact", "title": f"Add measurable results to {unquant} bullet(s)", "detail": "Only " + str(im_stats["quantified_pct"]) + "% of your bullets have a number. Add your real figures: users, % improvement, time saved, dataset size, rank, money.", "gain": max(1, round(gain))})
        if im_stats["action_pct"] < 85:
            gain = 0.45 * (1 - min(1, im_stats["action_pct"] / 85)) * w["impact"] * 100
            out.append({"area": "impact", "title": "Start every bullet with an action verb", "detail": f"{100 - im_stats['action_pct']}% of bullets open with something weaker ('Responsible for', 'Worked on', a noun).", "gain": max(1, round(gain))})
    by_cat = {"format": [c for c in checks if c.category == "format"], "sections": [c for c in checks if c.category == "sections"]}
    for cat, cs in by_cat.items():
        tw = sum(c.weight for c in cs) or 1
        for c in cs:
            if c.status != "pass" and c.fix:
                gain = (1 - c.value) * c.weight / tw * w[cat] * 100
                out.append({"area": cat, "title": c.label + (" (blocks parsing)" if c.id == "parse" else ""), "detail": f"{c.detail} {c.fix}", "gain": max(1, round(gain if c.id != "parse" else 60))})
    return sorted(out, key=lambda x: -x["gain"])


def _gaps(kw, checks, im_stats, ind, with_jd) -> list[str]:
    gaps = []
    req = [m["term"] for m in kw["missing"] if m["importance"] == "required" and not m["soft"]]
    if req:
        gaps.append(f"Required by the job but not on your resume: {', '.join(req[:8])}.")
    other = [m["term"] for m in kw["missing"] if m["importance"] != "required" and not m["soft"]]
    if other:
        gaps.append(f"{'Other job' if with_jd else 'Common ' + ind.name.lower()} keywords you don't show: {', '.join(other[:8])}.")
    for c in checks:
        if c.status == "fail":
            gaps.append(f"{c.label}: {c.detail}")
    if im_stats.get("bullets") and im_stats["quantified_pct"] < 30:
        gaps.append(f"Few results: only {im_stats['quantified_pct']}% of bullets show an outcome a recruiter can measure.")
    return gaps


# ---------------------------------------------------------------- original vs tailored


def compare(original: ResumeView, tailored: ResumeView, industry_key: str | None, job_title: str, job_description: str) -> dict:
    a = score(original, industry_key, job_title, job_description)
    key = industry_key or a["industry"]
    b = score(tailored, key, job_title, job_description)
    had = {m["term"] for m in a["keywords"]["matched"]}
    has = {m["term"] for m in b["keywords"]["matched"]}
    ctx_a = {m["term"] for m in a["keywords"]["matched"] if m["in_context"]}
    ctx_b = {m["term"] for m in b["keywords"]["matched"] if m["in_context"]}
    return {
        "industry": key,
        "industry_name": a["industry_name"],
        "original": a,
        "tailored": b,
        "delta": b["score"] - a["score"],
        "keywords_gained": sorted(has - had),
        "keywords_now_in_context": sorted((ctx_b - ctx_a) & has),
        "keywords_still_missing": [m["term"] for m in b["keywords"]["missing"] if not m["soft"]][:12],
    }


def available_industries() -> list[dict]:
    return [{"key": k, "name": i.name} for k, i in INDUSTRIES.items()]


__all__ = ["SKILLS", "available_industries", "compare", "detect_industry", "score", "view_from_doc", "view_from_resume"]


def tailored_score(resume: ResumeData, match) -> int:
    """The ATS score of the exact resume that would be sent for this job (the tailored document) against the job."""
    from app.services import resume_doc

    doc = resume_doc.build(resume, match)
    return score(view_from_doc(doc, resume), None, match.job.title, match.job.description)["score"]

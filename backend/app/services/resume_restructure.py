"""Turns a messy resume (PDF text with icon glyphs, words split across lines, stacks typed as bullets, projects as one
long paragraph) into a properly structured one: contact line, summary, grouped skills, roles with title, company,
location, dates, bullets and stack, projects, education, certifications.

Nothing is reworded or invented. The AI only moves the resume's own words into the right places; every bullet it
returns is checked against the source text, and any source line that didn't make it in is reported back.
Without the AI, a layout-aware parser does the same job.
"""

import re

from app.llm import CallContext, LLMOutputError, LLMUnavailable, get_llm
from app.logging import log
from app.schemas import EducationItem, ExperienceItem, ProjectItem, ResumeData, SkillGroup
from app.skills import canonicalize, extract_skills

# ---------- text clean-up ----------

_PRIVATE_USE = re.compile("[-\U000f0000-\U000fffff]")
_CONTACT_AHEAD = r"(?=[\w.+-]+@|\+?\(?\d|X{3}|(?:www\.)?[\w-]+\.(?:com|in|io|dev|me|org|net|co|app)\b|https?://)"
# A lone icon character in front of an email, phone or link ("ć xxx@gmail.com | Ħ 98...").
_ICON = re.compile(r"(^|\|)\s*[^\s|]\s+" + _CONTACT_AHEAD)
_BULLET_START = re.compile(r"^\s*(?:[•\-\*–▪●◦➢►▶✓✔○■□➤]|o\s|\d{1,2}[.)]\s)")
_LABEL = re.compile(r"^[A-Z][\w &/+.-]{1,32}:\s")
_DATE = r"(?:(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+)?(?:19|20)\d{2}|present|current|now|ongoing"
DATE_RANGE = re.compile(rf"\(?\b({_DATE})\s*(?:-|–|—|to)\s*({_DATE})\b\)?", re.IGNORECASE)
_ONE_DATE = re.compile(rf"\(?\b({_DATE})\b\)?\s*$", re.IGNORECASE)

SECTIONS = {
    "summary": r"(professional\s+|career\s+)?(summary|profile|objective)|about me",
    "skills": r"(technical\s+|key\s+|core\s+)?skills(\s*(&|and)\s*\w+)?|technologies|tech stack",
    "experience": r"(work\s+|professional\s+|industry\s+)?experience|internships?|employment|work history",
    "projects": r"(academic\s+|personal\s+|key\s+|major\s+)?projects?(\s+work)?|project work",
    "education": r"education|academics|academic (details|qualifications)|qualifications",
    "certifications": r"(awards|certificates|certifications|achievements|honou?rs|accomplishments|extra[- ]?curricular|positions of responsibility|leadership)"
    r"(\s*(&|and|,)\s*(awards|certificates|certifications|achievements|honou?rs|activities))*",
}
_SECTION = re.compile(r"^\s*(" + "|".join(f"(?P<{k}>{v})" for k, v in SECTIONS.items()) + r")\s*:?\s*$", re.IGNORECASE)


def _section_of(line: str) -> str | None:
    m = _SECTION.match(line)
    if not m:
        return None
    return next(k for k in SECTIONS if m.group(k))


def clean_text(text: str) -> tuple[str, dict]:
    """Repairs what PDF extraction breaks, and counts each fix for the report."""
    fixes = {"icons": 0, "split_words": 0, "joined_lines": 0}
    text = text.replace("­", "").replace("\r", "")
    fixes["icons"] += len(_PRIVATE_USE.findall(text))
    text = _PRIVATE_USE.sub(" ", text)

    # Words hyphenated across a line break ("Kuber-\nnetes"), unless the hyphenated form is used elsewhere ("full-stack").
    def join_word(m: re.Match) -> str:
        a, b = m.group(1), m.group(2)
        if re.search(rf"\b{re.escape(a)}-{re.escape(b)}\b", text):
            return f"{a}-{b}"
        fixes["split_words"] += 1
        return a + b

    text = re.sub(r"(\w+)-\n\s*([a-z]\w*)", join_word, text)

    # Letters the PDF kerned apart ("T ensorFlow"), only where the joined word is a known skill or used elsewhere.
    def join_kern(m: re.Match) -> str:
        word = m.group(1) + m.group(2)
        if extract_skills(word) or re.search(rf"\b{re.escape(word)}\b", text):
            fixes["split_words"] += 1
            return word
        return m.group(0)

    text = re.sub(r"\b([A-Z]) ([a-z]{2,}[A-Za-z]*)\b", join_kern, text)

    lines: list[str] = []
    for raw in text.split("\n"):
        ln = re.sub(r"[ \t]+", " ", raw).strip()
        if not ln:
            continue
        if "@" in ln or "|" in ln or re.search(r"linkedin|github", ln, re.I):
            new = _ICON.sub(lambda m: (m.group(1) + " ") if m.group(1) else "", ln).strip()
            if new != ln:
                fixes["icons"] += 1
            ln = re.sub(r"\s*\|\s*", " | ", new).strip(" |")
        # A line wrapped from the one above (long line, no full stop, and this one isn't a heading, bullet, date line or label).
        prev = lines[-1] if lines else ""
        if (
            prev
            and len(prev) >= 70
            and not prev.endswith((".", ":", ";"))
            and not _BULLET_START.match(ln)
            and not _section_of(ln)
            and not _section_of(prev)
            and not DATE_RANGE.search(ln)
            and not _LABEL.match(ln)
        ):
            lines[-1] = f"{prev} {ln}"
            fixes["joined_lines"] += 1
            continue
        lines.append(ln)
    return "\n".join(lines), fixes


# ---------- pieces shared by both paths ----------

_TITLE_WORDS = re.compile(
    r"\b(engineer|intern|developer|scientist|analyst|associate|manager|lead|consultant|designer|researcher|assistant|trainee|"
    r"member|volunteer|head|coordinator|fellow|architect|specialist|executive|officer|sde|swe|programmer|tester|administrator|"
    r"representative|founder|co-founder|president|secretary|mentor|tutor|teacher|apprentice)s?\b",
    re.IGNORECASE,
)
_DEGREE = re.compile(
    r"\b(b\.?\s?e\.?|b\.?\s?tech|m\.?\s?tech|b\.?\s?sc|m\.?\s?sc|b\.?\s?com|m\.?\s?com|bca|mca|mba|bba|b\.?\s?arch|ph\.?\s?d|"
    r"bachelor|master|diploma|class\s+(x|xii|10|12)|1[02]th|hsc|ssc|cbse|icse|pgdm|b\.?\s?pharm|m\.?\s?pharm|ll\.?b|b\.?\s?des)\b",
    re.IGNORECASE,
)
_GRADE = re.compile(r"\b(c?gpa|sgpa|cpi|percentage|marks)\b\s*:?\s*[\d.]+(\s*/\s*\d+)?|\b\d{2}(\.\d+)?\s*%", re.IGNORECASE)


def _split_items(text: str) -> list[str]:
    return [x.strip(" .") for x in re.split(r",|;|\s\|\s|•", text) if x.strip(" .")]


def is_tech_list(text: str) -> bool:
    """A bullet that is only a stack ("AWS, EC2, S3, Kafka, Docker"), not a sentence about work."""
    items = _split_items(re.sub(r"^(tech(nologies)?|stack|tools|tech stack|built with)\s*:\s*", "", text.strip(), flags=re.I))
    if len(items) < 3 or any(len(x.split()) > 4 for x in items):
        return False
    known = sum(1 for x in items if extract_skills(x))
    return known / len(items) >= 0.5


def tech_items(text: str) -> list[str]:
    items = _split_items(re.sub(r"^(tech(nologies)?|stack|tools|tech stack|built with)\s*:\s*", "", text.strip(), flags=re.I))
    # Kept as written ("EC2" stays "EC2"; canonicalizing would fold it into "AWS"), only the casing is normalized.
    return list(dict.fromkeys(_cased(x) for x in items))


def _cased(x: str) -> str:
    c = canonicalize(x)
    return c if c.lower().replace(".", "").replace(" ", "") == x.lower().replace(".", "").replace(" ", "") else x


def split_sentences(text: str) -> list[str]:
    """A paragraph-bullet into one bullet per sentence. Short bullets are left alone."""
    text = text.strip()
    parts = [p for p in re.split(r"(?<=[a-z0-9)%])\.\s+(?=[A-Z])", text) if p.strip()]
    # Three or more sentences is a paragraph; two short ones usually belong together.
    if len(parts) < 3 and (len(parts) < 2 or len(text.split()) < 34):
        return [text]
    out = [p.strip().rstrip(".") + "." for p in parts if len(p.split()) >= 3]
    return out or [text]


def _strip_trailing_stack(text: str) -> tuple[str, list[str]]:
    """'…using edit distance. Python, BeautifulSoup.' -> ('…using edit distance.', ['Python', 'BeautifulSoup'])."""
    m = re.search(r"(?:^|(?<=\.)\s+)([A-Z][^.]*?(?:,\s*[^.,]+)+)\.?\s*$", text)
    if not m:
        return text, []
    items = _split_items(m.group(1))
    short = len(items) >= 2 and all(len(x.split()) <= 3 for x in items) and any(extract_skills(x) for x in items)
    if is_tech_list(m.group(1)) or short:
        return text[: m.start(1)].strip(), tech_items(m.group(1))
    return text, []


def _org_location(text: str) -> tuple[str, str]:
    text = text.strip(" ,|-–—")
    if "," in text:
        org, loc = text.rsplit(",", 1)
        if len(loc.split()) <= 3:
            return org.strip(), loc.strip()
    return text, ""


def _dates(line: str) -> tuple[str, str, str]:
    """(line without dates, start, end)."""
    if m := DATE_RANGE.search(line):
        return (line[: m.start()] + line[m.end():]).strip(" |,-–—()"), m.group(1).strip(), m.group(2).strip()
    if m := _ONE_DATE.search(line):
        return line[: m.start()].strip(" |,-–—()"), "", m.group(1).strip()
    return line.strip(), "", ""


def _clean_bullet(b: str) -> str:
    return _BULLET_START.sub("", b).strip()


# ---------- offline parser (no AI) ----------


def layout_parse(text: str) -> ResumeData:
    """A parser for the common one-column layouts, including "Company, City   Dates / Title" headers."""
    from app.resume_parser import _EMAIL, _PHONE, _URL

    lines = text.split("\n")
    data = ResumeData()
    sections: dict[str, list[str]] = {}
    current = "header"
    for ln in lines:
        if key := _section_of(ln):
            current = key
            continue
        sections.setdefault(current, []).append(ln)

    header = sections.get("header", [])
    if header:
        data.name = header[0].strip()[:120]
    head_text = "\n".join(header[:6])
    if m := _EMAIL.search(head_text):
        data.email = m.group(0)
    if m := (_PHONE.search(head_text) or re.search(r"\+?X{3}[-\sX]+", head_text)):
        data.phone = m.group(0).strip()
    data.links = list(dict.fromkeys(u.rstrip(".,") for u in _URL.findall(head_text)))[:5]
    data.summary = " ".join(sections.get("summary", []))[:1200]

    for ln in sections.get("skills", []):
        ln = _clean_bullet(ln)
        if m := re.match(r"^([^:]{2,40}):\s*(.+)$", ln):
            data.skill_groups.append(SkillGroup(name=m.group(1).strip(), items=tech_items(m.group(2))))
        elif ln:
            data.skill_groups.append(SkillGroup(name="", items=tech_items(ln)))

    # Experience: header lines (one or two) then bullets.
    def blocks(key: str) -> list[tuple[list[str], list[str]]]:
        out: list[tuple[list[str], list[str]]] = []
        for ln in sections.get(key, []):
            if _BULLET_START.match(ln):
                if not out:
                    out.append(([], []))
                out[-1][1].append(_clean_bullet(ln))
            elif out and out[-1][1] and not ln[:1].isupper() and not DATE_RANGE.search(ln):
                out[-1][1][-1] += " " + ln
            elif out and not out[-1][1]:
                out[-1][0].append(ln)
            else:
                out.append(([ln], []))
        return out

    for heads, bullets in blocks("experience"):
        exp = ExperienceItem()
        rest: list[str] = []
        for h in heads:
            core, start, end = _dates(h)
            if (start or end) and not (exp.start or exp.end):
                exp.start, exp.end = start, end
            for part in [p.strip() for p in re.split(r"\s\|\s|\s+[–—]\s+|\s+at\s+", core) if p.strip()]:
                rest.append(part)
        titled = [p for p in rest if _TITLE_WORDS.search(p)]
        title = titled[0] if titled else (rest[1] if len(rest) > 1 else rest[0] if rest else "")
        others = [p for p in rest if p != title]
        exp.title = title
        if others:
            exp.organization, exp.location = _org_location(others[0])
            if len(others) > 1 and not exp.location:
                exp.location = others[1]
        for b in bullets:
            if is_tech_list(b):
                exp.tech += tech_items(b)
            else:
                exp.bullets += split_sentences(b)
        data.experience.append(exp)

    for heads, bullets in blocks("projects"):
        if heads:
            name, start, end = _dates(heads[0])
            parts = [p.strip() for p in name.split("|")]
            proj = ProjectItem(name=parts[0], tech=tech_items(", ".join(parts[1:])) if len(parts) > 1 else [])
            for b in bullets:
                if is_tech_list(b):
                    proj.tech += tech_items(b)
                else:
                    body, stack = _strip_trailing_stack(b)
                    proj.bullets += split_sentences(body)
                    proj.tech += stack
            data.projects.append(proj)
        else:
            # "• Name (Year): what it does…" — each bullet is its own project.
            for b in bullets:
                m = re.match(r"^([^:]{3,80}?):\s+(.+)$", b)
                if not m:
                    data.projects.append(ProjectItem(name="", bullets=split_sentences(b)))
                    continue
                body, stack = _strip_trailing_stack(m.group(2))
                data.projects.append(ProjectItem(name=m.group(1).strip(), tech=stack, bullets=split_sentences(body)))

    edu: EducationItem | None = None
    for ln in sections.get("education", []):
        ln = _clean_bullet(ln)
        core, start, end = _dates(ln)
        grade = _GRADE.search(core)
        if _DEGREE.search(core) and (edu is None or edu.degree):
            edu = EducationItem()
            data.education.append(edu)
        elif edu is None or (start or end) and (edu.start or edu.end):
            edu = EducationItem()
            data.education.append(edu)
        if start or end:
            edu.start, edu.end = start, end
        if grade:
            edu.details = "; ".join(x for x in (edu.details, grade.group(0).strip()) if x)
            core = (core[: grade.start()] + core[grade.end():]).strip(" ,|-–")
        if not core:
            continue
        if _DEGREE.search(core) and not edu.degree:
            edu.degree = core
        elif not edu.school and not _LABEL.match(core + " "):
            edu.school = core
        else:
            edu.details = "\n".join(x for x in (edu.details, core) if x)

    for ln in sections.get("certifications", []):
        if _BULLET_START.match(ln) or not data.certifications:
            data.certifications.append(_clean_bullet(ln))
        else:
            data.certifications[-1] += " " + ln
    return data


# ---------- AI path ----------

SYSTEM = """You restructure a resume into clean sections, using ONLY the resume's own words.
Rules (strict):
- Copy wording, numbers and technologies exactly. Never add, improve, summarize or invent anything. Fix only obvious
  line-break damage (a word split across lines).
- Experience: one entry per role with title, organization (company only), location, start, end. A bullet that only
  lists technologies goes into that role's "tech", not "bullets".
- Projects: one entry per project with its name (keep a year in brackets if given). If the resume writes a project as
  one long paragraph, split it into bullets at its sentence boundaries, keeping each sentence's words. Technologies
  listed at the end go into "tech".
- Skills: keep the resume's own groups (e.g. "Languages", "Technologies & Tools") in skill_groups, and list every
  skill in skills.
- Education: degree, school, start, end; CGPA/percentage and relevant coursework in details.
- Certifications, awards, achievements, positions of responsibility, mentoring: one line each in certifications.
- Leave summary empty unless the resume has one. Leave any absent field empty."""


_WORD = re.compile(r"[a-z0-9][a-z0-9+#.%$]*", re.IGNORECASE)


def _tokens(text: str) -> list[str]:
    return [w.lower().strip(".") for w in _WORD.findall(text) if len(w.strip(".")) >= 3]


def faithful(text: str, source_tokens: set[str]) -> bool:
    toks = _tokens(text)
    return not toks or sum(1 for t in toks if t in source_tokens) / len(toks) >= 0.9


def _all_strings(r: ResumeData) -> list[str]:
    out = [*r.skills, *r.certifications, r.summary]
    out += [x for g in r.skill_groups for x in g.items]
    for e in r.experience:
        out += [e.title, e.organization, e.location, e.start, e.end, *e.bullets, *e.tech]
    for p in r.projects:
        out += [p.name, *p.tech, *p.bullets]
    for e in r.education:
        out += [e.school, e.degree, e.start, e.end, e.details]
    return [x for x in out if x]


def tidy(r: ResumeData) -> ResumeData:
    """Final pass on either path: stacks out of bullets, paragraph bullets split, skills merged and de-duplicated."""
    for e in r.experience:
        keep: list[str] = []
        for b in e.bullets:
            if is_tech_list(b):
                e.tech += tech_items(b)
            else:
                keep += split_sentences(b)
        e.bullets = keep
        e.tech = list(dict.fromkeys(e.tech))
    for p in r.projects:
        keep = []
        for b in p.bullets:
            if is_tech_list(b):
                p.tech += tech_items(b)
            else:
                body, stack = _strip_trailing_stack(b)
                keep += split_sentences(body)
                p.tech += stack
        p.bullets = [b for b in keep if b]
        p.tech = list(dict.fromkeys(p.tech))
    r.skill_groups = [g for g in r.skill_groups if g.items]
    every = [*r.skills, *(x for g in r.skill_groups for x in g.items)]
    r.skills = list(dict.fromkeys(_cased(x.strip()) for x in every if x.strip()))
    r.certifications = [c.strip() for c in r.certifications if c.strip()]
    r.links = list(dict.fromkeys(r.links))[:5]
    return r


def _unplaced(source: str, r: ResumeData) -> list[str]:
    """Source lines whose words mostly didn't make it into the structured resume, so the student can check them."""
    have = set(_tokens(" ".join([r.name, r.email, r.phone, *r.links, *_all_strings(r)])))
    out = []
    for ln in source.split("\n"):
        toks = _tokens(ln)
        if len(toks) >= 4 and not _section_of(ln) and sum(1 for t in toks if t in have) / len(toks) < 0.6:
            out.append(_clean_bullet(ln))
    return out[:12]


def _section_list(r: ResumeData) -> list[str]:
    out = ["Contact"]
    out += ["Summary"] if r.summary else []
    out += ["Skills"] if r.skills else []
    out += [f"Experience ({len(r.experience)})"] if r.experience else []
    out += [f"Projects ({len(r.projects)})"] if r.projects else []
    out += ["Education"] if r.education else []
    out += ["Certifications & awards"] if r.certifications else []
    return out


async def restructure(text: str, ctx: CallContext, *, base: ResumeData | None = None) -> tuple[ResumeData, dict]:
    """(structured resume, report). `base` keeps what the student added in JobPilot (confirmed skills)."""
    clean, fixes = clean_text(text)
    source_tokens = set(_tokens(clean))
    ai = False
    try:
        data = await get_llm().structured(
            agent="resume_parser",
            tier="smart",
            system=SYSTEM,
            prompt=f"<resume>\n{clean[:30000]}\n</resume>",
            schema=ResumeData,
            ctx=ctx,
            max_tokens=6000,
        )
        ai = True
    except (LLMUnavailable, LLMOutputError) as exc:
        log.info("resume.restructure_offline", reason=str(exc)[:200])
        data = layout_parse(clean)

    dropped = 0
    if ai:
        # Every AI bullet must be made of the resume's own words.
        for e in data.experience:
            kept = [b for b in e.bullets if faithful(b, source_tokens)]
            dropped += len(e.bullets) - len(kept)
            e.bullets = kept
        for p in data.projects:
            kept = [b for b in p.bullets if faithful(b, source_tokens)]
            dropped += len(p.bullets) - len(kept)
            p.bullets = kept
        kept = [c for c in data.certifications if faithful(c, source_tokens)]
        dropped += len(data.certifications) - len(kept)
        data.certifications = kept
        data.summary = data.summary if faithful(data.summary, source_tokens) else ""
        # Contact details the AI sometimes skips.
        offline = layout_parse(clean)
        data.name = data.name or offline.name
        data.email = data.email or offline.email
        data.phone = data.phone or offline.phone
        data.links = data.links or offline.links
        if not data.certifications and offline.certifications:
            data.certifications = offline.certifications
        if not data.skill_groups and offline.skill_groups:
            data.skill_groups = offline.skill_groups
    data = tidy(data)
    data.skills = list(dict.fromkeys([*data.skills, *extract_skills(clean)]))
    if base is not None:
        data.additional = base.additional
        data.location = data.location or base.location

    unplaced = _unplaced(clean, data)
    notes: list[str] = []
    if fixes["icons"]:
        notes.append(f"Removed {fixes['icons']} icon symbol{'s' if fixes['icons'] > 1 else ''} that ATS software reads as junk characters.")
    if fixes["split_words"]:
        notes.append(f"Rejoined {fixes['split_words']} word{'s' if fixes['split_words'] > 1 else ''} the PDF had split (e.g. \"Kuber-netes\").")
    stacks = sum(1 for e in data.experience if e.tech) + sum(1 for p in data.projects if p.tech)
    if stacks:
        notes.append(f"Moved the tech stack of {stacks} role{'s' if stacks > 1 else ''}/project{'s' if stacks > 1 else ''} out of the bullets onto its own \"Tech\" line.")
    if any(e.location for e in data.experience):
        notes.append("Each role now reads Title · Company, Location · Dates, the order recruiters and ATS expect.")
    if data.skill_groups:
        notes.append(f"Kept your skills in {len(data.skill_groups)} labelled group{'s' if len(data.skill_groups) > 1 else ''}.")
    if data.certifications:
        notes.append(f"Put {len(data.certifications)} certification/award line{'s' if len(data.certifications) > 1 else ''} under their own heading.")
    if dropped:
        notes.append(f"Left out {dropped} AI line{'s' if dropped > 1 else ''} that didn't match your resume's wording.")
    return data, {"ai": ai, "notes": notes, "unplaced": unplaced, "sections": _section_list(data), "fixes": fixes}

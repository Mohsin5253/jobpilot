"""Resume file -> text -> structured ResumeData (Claude first, heuristic section parser as fallback)."""

import io
import re

from app.llm import CallContext, LLMOutputError, LLMUnavailable, get_llm
from app.logging import log
from app.schemas import EducationItem, ExperienceItem, ProjectItem, ResumeData
from app.skills import canonicalize, extract_skills

MAX_RESUME_BYTES = 5 * 1024 * 1024


class UnsupportedResume(ValueError):
    pass


def extract_text(filename: str, data: bytes) -> str:
    name = filename.lower()
    if name.endswith(".pdf"):
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        text = "\n".join((page.extract_text() or "") for page in reader.pages)
    elif name.endswith(".docx"):
        from docx import Document

        doc = Document(io.BytesIO(data))
        text = "\n".join(p.text for p in doc.paragraphs)
    elif name.endswith((".txt", ".md")):
        text = data.decode("utf-8", errors="replace")
    else:
        raise UnsupportedResume("Upload a PDF, DOCX, TXT or MD file")
    text = re.sub(r"[ \t]+", " ", text).strip()
    if len(text) < 80:
        raise UnsupportedResume("Could not read text from this file (is it a scanned image?)")
    return text


SYSTEM = """You convert resumes into structured JSON.
Copy content faithfully: keep every bullet's wording, numbers and technologies exactly as written.
Do not summarize, merge, improve or invent anything. If a field is absent, leave it empty.
Put coursework/research/hackathon work with its own bullets under projects."""


async def structure_resume(text: str, ctx: CallContext) -> ResumeData:
    try:
        data = await get_llm().structured(
            agent="resume_parser",
            tier="smart",
            system=SYSTEM,
            prompt=f"<resume>\n{text[:30000]}\n</resume>",
            schema=ResumeData,
            ctx=ctx,
        )
    except (LLMUnavailable, LLMOutputError) as exc:
        log.info("resume.heuristic_parse", reason=str(exc)[:200])
        data = heuristic_parse(text)
    # Skills listed anywhere in the resume count, normalized to the shared lexicon.
    merged = list(dict.fromkeys([*(canonicalize(x) for x in data.skills if x.strip()), *extract_skills(text)]))
    data.skills = merged
    return data


_SECTION = re.compile(
    r"^\s*(summary|profile|objective|skills|technical skills|experience|work experience|internships?|"
    r"projects?|academic projects|education|certifications?|achievements|awards)\s*:?\s*$",
    re.IGNORECASE,
)
_BULLET = re.compile(r"^\s*[•\-\*–▪●◦]\s*")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
_PHONE = re.compile(r"\+?\d[\d\s\-()]{8,}\d")
_URL = re.compile(r"(https?://\S+|(?:linkedin|github)\.com/\S+)", re.IGNORECASE)


def heuristic_parse(text: str) -> ResumeData:
    lines = [ln.rstrip() for ln in text.splitlines() if ln.strip()]
    data = ResumeData()
    if lines:
        data.name = lines[0].strip()[:120]
    if m := _EMAIL.search(text):
        data.email = m.group(0)
    if m := _PHONE.search(text):
        data.phone = m.group(0).strip()
    data.links = list(dict.fromkeys(_URL.findall(text)))[:5]

    sections: dict[str, list[str]] = {}
    current = "header"
    for ln in lines:
        if m := _SECTION.match(ln):
            key = m.group(1).lower()
            current = (
                "skills" if "skill" in key
                else "experience" if ("experience" in key or "intern" in key)
                else "projects" if "project" in key
                else "education" if "education" in key
                else "summary" if key in ("summary", "profile", "objective")
                else "other"
            )
            continue
        sections.setdefault(current, []).append(ln)

    data.summary = " ".join(sections.get("summary", []))[:1000]
    data.skills = extract_skills(" ".join(sections.get("skills", [])))

    def blocks(key: str) -> list[tuple[str, list[str]]]:
        out: list[tuple[str, list[str]]] = []
        for ln in sections.get(key, []):
            if _BULLET.match(ln):
                if not out:
                    out.append(("", []))
                out[-1][1].append(_BULLET.sub("", ln).strip())
            elif out and out[-1][1] and not ln[:1].isupper():
                out[-1][1][-1] += " " + ln.strip()  # wrapped bullet line
            else:
                out.append((ln.strip(), []))
        return [(h, b) for h, b in out if h or b]

    for header, bullets in blocks("experience"):
        title, _, org = header.partition(" at ") if " at " in header else header.partition("|")
        data.experience.append(ExperienceItem(title=title.strip(), organization=org.strip(), bullets=bullets))
    for header, bullets in blocks("projects"):
        data.projects.append(ProjectItem(name=header.split("|")[0].strip(), tech=extract_skills(header), bullets=bullets))
    for ln in sections.get("education", [])[:4]:
        data.education.append(EducationItem(school=ln.strip()))
    return data

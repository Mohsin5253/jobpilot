"""Tailored resume documents (PDF + DOCX) for one job, built from the resume you uploaded.

What changes per job: skills that job asks for (and you have) move to the front, the Tailor's
guard-checked rewrites replace the original bullets and the most relevant bullets go first, and skills
you confirmed in Skill check appear in their own section in your words. Nothing outside your profile is
ever added; skills you lack stay out (the Interviewer asks about them instead).
"""

import io
import re
from dataclasses import dataclass, field

from app.models import JobMatch
from app.schemas import ResumeData


@dataclass
class Section:
    heading: str
    meta: str = ""
    bullets: list[str] = field(default_factory=list)


@dataclass
class TailoredDoc:
    name: str
    contact: str
    summary: str
    key_skills: list[str]
    other_skills: list[str]
    experience: list[Section]
    projects: list[Section]
    additional: list[str]
    education: list[str]
    target: str  # "Software Development Engineer Intern — HackerRank"
    variant: str = "A"  # A: experience first (skills-led) · B: projects first — compared on the Insights page

    def body_sections(self) -> tuple[tuple[str, list[Section]], ...]:
        pair = (("Experience", self.experience), ("Projects", self.projects))
        return pair[::-1] if self.variant == "B" else pair


def build(resume: ResumeData, match: JobMatch | None) -> TailoredDoc:
    job = match.job if match else None
    wanted = {s.lower() for s in ([*(job.skills or []), *match.strengths] if match else [])}
    key = [s for s in resume.skills if s.lower() in wanted]
    other = [s for s in resume.skills if s.lower() not in wanted]

    rewrites: dict[str, str] = {}
    if match and match.tailored:
        rewrites = {b["source_id"]: b["rewritten"] for b in match.tailored.bullets if not b.get("reverted") and not b.get("declined")}
    priority = list(rewrites)  # Tailor's order = relevance order

    def ordered(prefix: str, bullets: list[str]) -> list[str]:
        ids = [f"{prefix}.b{j}" for j in range(len(bullets))]
        ids.sort(key=lambda i: priority.index(i) if i in priority else len(priority))
        return [rewrites.get(i, bullets[int(i.rsplit("b", 1)[1])]) for i in ids]

    experience = [
        Section(heading=" — ".join(x for x in (e.title, e.organization) if x), meta=" – ".join(x for x in (e.start, e.end) if x), bullets=ordered(f"exp{i}", e.bullets))
        for i, e in enumerate(resume.experience)
    ]
    projects = [
        Section(heading=p.name, meta=", ".join(p.tech), bullets=ordered(f"proj{i}", p.bullets)) for i, p in enumerate(resume.projects)
    ]
    # Projects with tailored bullets go first.
    projects.sort(key=lambda sec: 0 if any(b in rewrites.values() for b in sec.bullets) else 1)
    additional = [rewrites.get(f"add{i}", f"{a.skill}: {a.details}") for i, a in enumerate(resume.additional) if a.details.strip()]
    education = [" · ".join(x for x in (e.degree, e.school, " – ".join(y for y in (e.start, e.end) if y)) if x) for e in resume.education]

    return TailoredDoc(
        name=resume.name or "Resume",
        contact=" | ".join(x for x in (resume.email, resume.phone, resume.location, *resume.links[:3]) if x),
        summary=resume.summary,
        key_skills=key,
        other_skills=other,
        experience=experience,
        projects=projects,
        additional=additional,
        education=education,
        target=f"{job.title} — {job.company}" if job else "",
        variant=getattr(match, "resume_variant", "A") or "A",
    )


def filename(doc: TailoredDoc, ext: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9]+", "_", f"{doc.name} {doc.target}").strip("_")[:90]
    return f"{stem or 'resume'}.{ext}"


def render_pdf(doc: TailoredDoc) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import HRFlowable, ListFlowable, ListItem, Paragraph, SimpleDocTemplate, Spacer
    from xml.sax.saxutils import escape as esc

    ink, muted, accent = colors.HexColor("#111118"), colors.HexColor("#555566"), colors.HexColor("#4B3BCC")
    st = {
        "name": ParagraphStyle("name", fontName="Helvetica-Bold", fontSize=18, leading=22, alignment=TA_CENTER, textColor=ink),
        "contact": ParagraphStyle("contact", fontName="Helvetica", fontSize=8.5, leading=11, alignment=TA_CENTER, textColor=muted),
        "h": ParagraphStyle("h", fontName="Helvetica-Bold", fontSize=10, leading=13, textColor=accent, spaceBefore=8, spaceAfter=2),
        "role": ParagraphStyle("role", fontName="Helvetica-Bold", fontSize=9.5, leading=12, textColor=ink, spaceBefore=3),
        "meta": ParagraphStyle("meta", fontName="Helvetica-Oblique", fontSize=8.5, leading=11, textColor=muted),
        "body": ParagraphStyle("body", fontName="Helvetica", fontSize=9.2, leading=12.2, textColor=ink),
    }
    buf = io.BytesIO()
    pdf = SimpleDocTemplate(buf, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm, topMargin=13 * mm, bottomMargin=13 * mm, title=f"{doc.name} — {doc.target}", author=doc.name)
    story: list = [Paragraph(esc(doc.name), st["name"]), Paragraph(esc(doc.contact), st["contact"]), Spacer(1, 4)]

    def heading(text: str) -> None:
        story.extend([Paragraph(text.upper(), st["h"]), HRFlowable(width="100%", thickness=0.6, color=colors.HexColor("#DDDDE6"), spaceAfter=3)])

    def bullets(items: list[str]) -> None:
        if items:
            story.append(
                ListFlowable([ListItem(Paragraph(esc(b), st["body"]), leftIndent=10) for b in items], bulletType="bullet", start="•", leftIndent=10, bulletFontSize=8)
            )

    if doc.summary:
        heading("Summary")
        story.append(Paragraph(esc(doc.summary), st["body"]))
    if doc.key_skills or doc.other_skills:
        heading("Skills")
        if doc.key_skills:
            story.append(Paragraph(f"<b>Relevant to this role:</b> {esc(', '.join(doc.key_skills))}", st["body"]))
        if doc.other_skills:
            story.append(Paragraph(f"<b>{'Also' if doc.key_skills else 'Skills'}:</b> {esc(', '.join(doc.other_skills))}", st["body"]))
    for title, sections in doc.body_sections():
        if sections:
            heading(title)
            for sec in sections:
                story.append(Paragraph(esc(sec.heading), st["role"]))
                if sec.meta:
                    story.append(Paragraph(esc(sec.meta), st["meta"]))
                bullets(sec.bullets)
    if doc.additional:
        heading("Additional experience")
        bullets(doc.additional)
    if doc.education:
        heading("Education")
        for e in doc.education:
            story.append(Paragraph(esc(e), st["body"]))
    pdf.build(story)
    return buf.getvalue()


def render_docx(doc: TailoredDoc) -> bytes:
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt, RGBColor

    d = Document()
    style = d.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(10)
    for section in d.sections:
        section.left_margin = section.right_margin = section.top_margin = section.bottom_margin = Pt(46)

    p = d.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run(doc.name)
    r.bold, r.font.size = True, Pt(18)
    c = d.add_paragraph(doc.contact)
    c.alignment = WD_ALIGN_PARAGRAPH.CENTER

    def heading(text: str) -> None:
        h = d.add_paragraph()
        run = h.add_run(text.upper())
        run.bold, run.font.size, run.font.color.rgb = True, Pt(10.5), RGBColor(0x4B, 0x3B, 0xCC)

    def bullets(items: list[str]) -> None:
        for b in items:
            d.add_paragraph(b, style="List Bullet")

    if doc.summary:
        heading("Summary")
        d.add_paragraph(doc.summary)
    if doc.key_skills or doc.other_skills:
        heading("Skills")
        if doc.key_skills:
            para = d.add_paragraph()
            para.add_run("Relevant to this role: ").bold = True
            para.add_run(", ".join(doc.key_skills))
        if doc.other_skills:
            para = d.add_paragraph()
            para.add_run("Also: " if doc.key_skills else "Skills: ").bold = True
            para.add_run(", ".join(doc.other_skills))
    for title, sections in doc.body_sections():
        if sections:
            heading(title)
            for sec in sections:
                para = d.add_paragraph()
                para.add_run(sec.heading).bold = True
                if sec.meta:
                    para.add_run(f"   {sec.meta}").italic = True
                bullets(sec.bullets)
    if doc.additional:
        heading("Additional experience")
        bullets(doc.additional)
    if doc.education:
        heading("Education")
        for e in doc.education:
            d.add_paragraph(e)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()

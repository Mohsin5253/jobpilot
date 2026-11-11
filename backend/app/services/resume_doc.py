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
    meta: str = ""  # dates, right-aligned
    bullets: list[str] = field(default_factory=list)
    sub: str = ""  # "Adobe, Bangalore"
    tech: str = ""  # "AWS, Kafka, Docker"
    details: list[str] = field(default_factory=list)  # education: CGPA, coursework

    @property
    def title_line(self) -> str:
        return " — ".join(x for x in (self.heading, self.sub) if x)


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
    skill_groups: list[tuple[str, list[str]]] = field(default_factory=list)
    education_items: list[Section] = field(default_factory=list)
    certifications: list[str] = field(default_factory=list)

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

    def span(a: str, b: str) -> str:
        return " – ".join(x for x in (a, b) if x)

    experience = [
        Section(
            heading=e.title or e.organization,
            sub=", ".join(x for x in ((e.organization if e.title else ""), e.location) if x),
            meta=span(e.start, e.end),
            bullets=ordered(f"exp{i}", e.bullets),
            tech=", ".join(e.tech),
        )
        for i, e in enumerate(resume.experience)
    ]
    projects = [Section(heading=p.name, bullets=ordered(f"proj{i}", p.bullets), tech=", ".join(p.tech)) for i, p in enumerate(resume.projects)]
    # Projects with tailored bullets go first.
    projects.sort(key=lambda sec: 0 if any(b in rewrites.values() for b in sec.bullets) else 1)
    additional = [rewrites.get(f"add{i}", f"{a.skill}: {a.details}") for i, a in enumerate(resume.additional) if a.details.strip()]
    education = [" · ".join(x for x in (e.degree, e.school, span(e.start, e.end), e.details.replace("\n", "; ")) if x) for e in resume.education]
    education_items = [
        Section(heading=e.degree or e.school, sub=e.school if e.degree else "", meta=span(e.start, e.end), details=[d.strip() for d in e.details.split("\n") if d.strip()])
        for e in resume.education
    ]
    # Without a target job, skills keep the resume's own groups ("Languages: …"); anything ungrouped goes last.
    groups: list[tuple[str, list[str]]] = []
    if not match and resume.skill_groups:
        from app.skills import canonicalize

        grouped = {k for g in resume.skill_groups for x in g.items for k in (x.lower(), canonicalize(x).lower())}
        groups = [(g.name or "Skills", list(g.items)) for g in resume.skill_groups if g.items]
        rest = [x for x in resume.skills if x.lower() not in grouped and canonicalize(x).lower() not in grouped]
        if rest:
            groups.append(("Other", rest))

    return TailoredDoc(
        name=resume.name or "Resume",
        contact=" | ".join(x for x in (resume.email, resume.phone, resume.location, *resume.links[:3]) if x),
        summary=((match.tailored.guard_report or {}).get("summary") if match and match.tailored else None) or resume.summary,
        key_skills=key,
        other_skills=other,
        experience=experience,
        projects=projects,
        additional=additional,
        education=education,
        target=f"{job.title} — {job.company}" if job else "",
        variant=getattr(match, "resume_variant", "A") or "A",
        skill_groups=groups,
        education_items=education_items,
        certifications=list(resume.certifications),
    )


def filename(doc: TailoredDoc, ext: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9]+", "_", f"{doc.name} {doc.target}").strip("_")[:90]
    return f"{stem or 'resume'}.{ext}"


_PDF_MAP = str.maketrans({"\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2212": "-", "\u00a0": " ", "\u202f": " ", "\u2009": " ", "\u200b": ""})


def pdf_safe(text: str) -> str:
    """The PDF's built-in fonts cover Windows-1252 only; anything else would print as a black box."""
    import unicodedata

    text = text.translate(_PDF_MAP)
    out = []
    for ch in text:
        try:
            ch.encode("cp1252")
            out.append(ch)
        except UnicodeEncodeError:
            out.append(unicodedata.normalize("NFKD", ch).encode("cp1252", "ignore").decode("cp1252"))
    return "".join(out)


def _skill_lines(doc: TailoredDoc) -> list[tuple[str, str]]:
    if doc.skill_groups:
        return [(name, ", ".join(items)) for name, items in doc.skill_groups]
    out = []
    if doc.key_skills:
        out.append(("Relevant to this role", ", ".join(doc.key_skills)))
    if doc.other_skills:
        out.append(("Also" if doc.key_skills else "Skills", ", ".join(doc.other_skills)))
    return out


def render_pdf(doc: TailoredDoc) -> bytes:
    """A4, one column, real text (no tables, images or icons). Every role, project and degree is kept on one page;
    headings never sit alone at the bottom of a page."""
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.pdfbase.pdfmetrics import stringWidth
    from reportlab.platypus import Flowable, HRFlowable, KeepTogether, ListFlowable, ListItem, Paragraph, SimpleDocTemplate, Spacer
    from xml.sax.saxutils import escape as _esc

    def esc(t: str) -> str:
        return _esc(pdf_safe(t))

    ink, muted, accent = colors.HexColor("#111118"), colors.HexColor("#555566"), colors.HexColor("#2F3A8F")
    st = {
        "name": ParagraphStyle("name", fontName="Helvetica-Bold", fontSize=18, leading=22, alignment=TA_CENTER, textColor=ink),
        "contact": ParagraphStyle("contact", fontName="Helvetica", fontSize=8.6, leading=11, alignment=TA_CENTER, textColor=muted),
        "h": ParagraphStyle("h", fontName="Helvetica-Bold", fontSize=10.2, leading=13, textColor=accent, spaceBefore=8, spaceAfter=1, keepWithNext=1),
        "role": ParagraphStyle("role", fontName="Helvetica-Bold", fontSize=9.6, leading=12, textColor=ink, spaceBefore=4, keepWithNext=1),
        "meta": ParagraphStyle("meta", fontName="Helvetica-Oblique", fontSize=8.6, leading=11, textColor=muted, keepWithNext=1),
        "body": ParagraphStyle("body", fontName="Helvetica", fontSize=9.2, leading=12.2, textColor=ink),
        "tech": ParagraphStyle("tech", fontName="Helvetica", fontSize=8.6, leading=11, textColor=muted, leftIndent=10, spaceBefore=1),
    }
    width = A4[0] - 32 * mm

    class TitleLine(Flowable):
        """Bold title (and company) on the left, dates right-aligned on the same line: plain text, no table."""

        def __init__(self, left: str, sub: str, right: str):
            super().__init__()
            self.left, self.sub, self.right = pdf_safe(left), pdf_safe(sub), pdf_safe(right)

        def wrap(self, aw, ah):
            return aw, 13

        def draw(self):
            c = self.canv
            c.setFillColor(ink)
            c.setFont("Helvetica-Bold", 9.6)
            c.drawString(0, 3, self.left)
            x = stringWidth(self.left, "Helvetica-Bold", 9.6)
            if self.sub:
                c.setFont("Helvetica", 9.4)
                c.drawString(x, 3, f"  ·  {self.sub}")
            if self.right:
                c.setFillColor(muted)
                c.setFont("Helvetica-Oblique", 8.6)
                c.drawRightString(width, 3, self.right)

    def title_block(sec: Section) -> list:
        left_w = stringWidth(pdf_safe(sec.heading), "Helvetica-Bold", 9.6) + stringWidth(pdf_safe(f"  ·  {sec.sub}") if sec.sub else "", "Helvetica", 9.4)
        right_w = stringWidth(pdf_safe(sec.meta), "Helvetica-Oblique", 8.6)
        if left_w + right_w + 14 <= width:
            line = TitleLine(sec.heading, sec.sub, sec.meta)
            line.keepWithNext = 1
            return [Spacer(1, 3), line]
        out = [Paragraph(esc(sec.heading) + (f'<font name="Helvetica" size="9.4">  ·  {esc(sec.sub)}</font>' if sec.sub else ""), st["role"])]
        if sec.meta:
            out.append(Paragraph(esc(sec.meta), st["meta"]))
        return out

    buf = io.BytesIO()
    pdf = SimpleDocTemplate(buf, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm, topMargin=13 * mm, bottomMargin=13 * mm, title=" — ".join(x for x in (doc.name, doc.target) if x), author=doc.name)
    story: list = [Paragraph(esc(doc.name), st["name"]), Paragraph(esc(doc.contact), st["contact"]), Spacer(1, 4)]

    def heading(text: str) -> None:
        rule = HRFlowable(width="100%", thickness=0.6, color=colors.HexColor("#D5D7E3"), spaceBefore=0, spaceAfter=3)
        rule.keepWithNext = 1
        story.extend([Paragraph(text.upper(), st["h"]), rule])

    def bullet_list(items: list[str]):
        return ListFlowable([ListItem(Paragraph(esc(b), st["body"]), leftIndent=10) for b in items], bulletType="bullet", start="•", leftIndent=10, bulletFontSize=8)

    if doc.summary:
        heading("Summary")
        story.append(Paragraph(esc(doc.summary), st["body"]))
    if lines := _skill_lines(doc):
        heading("Skills")
        for label, items in lines:
            story.append(Paragraph(f"<b>{esc(label)}:</b> {esc(items)}", st["body"]))
    for title, sections in doc.body_sections():
        if sections:
            heading(title)
            for sec in sections:
                # One role or project is one unit: it moves to the next page whole rather than leaving its title behind.
                block = title_block(sec)
                if sec.bullets:
                    block.append(bullet_list(sec.bullets))
                if sec.tech:
                    block.append(Paragraph(f"<b>Tech:</b> {esc(sec.tech)}", st["tech"]))
                story.append(KeepTogether(block))
    if doc.additional:
        heading("Additional experience")
        story.append(bullet_list(doc.additional))
    if doc.education_items:
        heading("Education")
        for sec in doc.education_items:
            block = title_block(sec)
            block += [Paragraph(esc(d), st["body"]) for d in sec.details]
            story.append(KeepTogether(block))
    if doc.certifications:
        heading("Certifications & awards")
        story.append(bullet_list(doc.certifications))
    pdf.build(story)
    return buf.getvalue()


def render_docx(doc: TailoredDoc) -> bytes:
    """A4, one column, tight consistent spacing: headings stay with their content, a role never splits across pages."""
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Mm, Pt, RGBColor

    d = Document()
    sec = d.sections[0]
    sec.page_width, sec.page_height = Mm(210), Mm(297)
    sec.left_margin = sec.right_margin = Mm(16)
    sec.top_margin = sec.bottom_margin = Mm(13)
    text_width = sec.page_width - sec.left_margin - sec.right_margin
    d.core_properties.title = " — ".join(x for x in (doc.name, doc.target) if x)
    d.core_properties.author = doc.name

    normal = d.styles["Normal"]
    normal.font.name = "Calibri"
    normal.font.size = Pt(10)
    normal.element.rPr.rFonts.set(qn("w:eastAsia"), "Calibri")
    pf = normal.paragraph_format
    pf.space_before, pf.space_after, pf.line_spacing = Pt(0), Pt(1.5), 1.0
    lb = d.styles["List Bullet"].paragraph_format
    lb.space_before, lb.space_after, lb.line_spacing = Pt(0), Pt(1), 1.0

    ink, muted, accent = RGBColor(0x11, 0x11, 0x18), RGBColor(0x55, 0x55, 0x66), RGBColor(0x2F, 0x3A, 0x8F)

    def para(text: str = "", *, bold=False, italic=False, size=None, color=None, align=None, after=None, before=None, keep=False):
        p = d.add_paragraph()
        if text:
            r = p.add_run(text)
            r.bold, r.italic = bold, italic
            if size:
                r.font.size = Pt(size)
            if color is not None:
                r.font.color.rgb = color
        if align is not None:
            p.alignment = align
        if after is not None:
            p.paragraph_format.space_after = Pt(after)
        if before is not None:
            p.paragraph_format.space_before = Pt(before)
        p.paragraph_format.keep_with_next = keep
        p.paragraph_format.keep_together = True
        return p

    def rule_below(p) -> None:
        ppr = p._p.get_or_add_pPr()
        bdr = OxmlElement("w:pBdr")
        bottom = OxmlElement("w:bottom")
        for k, v in (("w:val", "single"), ("w:sz", "4"), ("w:space", "1"), ("w:color", "D5D7E3")):
            bottom.set(qn(k), v)
        bdr.append(bottom)
        ppr.append(bdr)

    para(doc.name, bold=True, size=17, color=ink, align=WD_ALIGN_PARAGRAPH.CENTER, after=0)
    para(doc.contact, size=8.5, color=muted, align=WD_ALIGN_PARAGRAPH.CENTER, after=4)

    def heading(text: str) -> None:
        h = para(text.upper(), bold=True, size=10.5, color=accent, before=8, after=2, keep=True)
        rule_below(h)

    def bullets(items: list[str], keep_last_with_next: bool = False) -> None:
        for i, b in enumerate(items):
            p = d.add_paragraph(b, style="List Bullet")
            p.paragraph_format.keep_together = True
            # Bullets of one role stay together with the role's title (Word's "keep with next").
            p.paragraph_format.keep_with_next = keep_last_with_next or i < len(items) - 1

    def title_line(s_: Section) -> None:
        # Title · company on the left, dates right-aligned on the same line.
        p = para(before=4, after=1, keep=True)
        p.paragraph_format.tab_stops.add_tab_stop(text_width, WD_TAB_ALIGNMENT.RIGHT)
        p.add_run(s_.heading).bold = True
        if s_.sub:
            p.add_run(f"  ·  {s_.sub}")
        if s_.meta:
            m = p.add_run(f"\t{s_.meta}")
            m.italic, m.font.size, m.font.color.rgb = True, Pt(9), muted

    def tech_line(text: str) -> None:
        p = para(size=None, after=1)
        p.paragraph_format.left_indent = Mm(4)
        r = p.add_run("Tech: ")
        r.bold, r.font.size, r.font.color.rgb = True, Pt(9), muted
        r = p.add_run(text)
        r.font.size, r.font.color.rgb = Pt(9), muted

    if doc.summary:
        heading("Summary")
        para(doc.summary)
    if lines := _skill_lines(doc):
        heading("Skills")
        for label, items in lines:
            p = para()
            p.add_run(f"{label}: ").bold = True
            p.add_run(items)
    for title, sections in doc.body_sections():
        if sections:
            heading(title)
            for s_ in sections:
                title_line(s_)
                bullets(s_.bullets, keep_last_with_next=bool(s_.tech))
                if s_.tech:
                    tech_line(s_.tech)
    if doc.additional:
        heading("Additional experience")
        bullets(doc.additional)
    if doc.education_items:
        heading("Education")
        for s_ in doc.education_items:
            title_line(s_)
            for i, det in enumerate(s_.details):
                para(det, keep=i < len(s_.details) - 1)
    if doc.certifications:
        heading("Certifications & awards")
        bullets(doc.certifications)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()

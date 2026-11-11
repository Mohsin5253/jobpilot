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
    # Skills in labelled groups like the sample ("Languages: …"): the resume's own groups, or grouped automatically.
    # For a job, the skills it asks for come first in each group, and every skill is printed (a recruiter's ATS
    # searches the file's text). Without a job, skills the resume's own groups leave out are listed only if
    # nothing else shows them, so the block stays as the student wrote it.
    from app.skills import canonicalize, group_skills

    groups: list[tuple[str, list[str]]] = []
    if resume.skill_groups:
        grouped = {k for g in resume.skill_groups for x in g.items for k in (x.lower(), canonicalize(x).lower())}
        groups = [(g.name or "Skills", list(g.items)) for g in resume.skill_groups if g.items]
        shown = " ".join([*(t for e in resume.experience for t in e.tech), *(t for p in resume.projects for t in p.tech), *(b for _, b in resume.bullet_index())]).lower()
        rest = [x for x in resume.skills if x.lower() not in grouped and canonicalize(x).lower() not in grouped and (match or x.lower() not in shown)]
        if rest and not match:
            groups.append(("Other", rest))
        elif rest:
            # For a job, extra skills (e.g. ones the student just confirmed) go into labelled groups too.
            names = {n for n, _ in groups}
            for name, items in group_skills(rest):
                if name in names:
                    groups = [(n, its + [x for x in items if x not in its]) if n == name else (n, its) for n, its in groups]
                else:
                    groups.append((name, items))
    elif resume.skills:
        groups = group_skills(resume.skills)
    if match:
        rank = {w: i for i, w in enumerate(x.lower() for x in key)}
        groups = [(name, sorted(items, key=lambda x: rank.get(x.lower(), len(rank)))) for name, items in groups]
        groups.sort(key=lambda g: min((rank.get(x.lower(), len(rank)) for x in g[1]), default=len(rank)))

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


# The layout follows the standard one-column engineering resume (the sample the product is built around):
# Skills, Work Experience, Education, Project Work, Awards and Certificates. Each role: "Company, City" bold with the
# dates right-aligned, the title in italics beneath, bullets, then the stack as the last bullet. Each project: one
# bullet led by its bold name. Real text throughout (no tables, columns, icons or images), so every ATS reads it.
HEADING = {"Experience": "Work Experience", "Projects": "Project Work"}


def _order(doc: TailoredDoc) -> list[str]:
    """Section order. Variant B (compared on the Insights page) leads with projects."""
    if doc.variant == "B":
        return ["Projects", "Experience", "Education"]
    return ["Experience", "Education", "Projects"]


def _role_lines(sec: Section) -> tuple[tuple[str, str], tuple[str, str]]:
    """((bold left, right), (italic left, right)) for a role: company line with dates, then the title."""
    if sec.sub:
        return (sec.sub, sec.meta), (sec.heading, "")
    return (sec.heading, sec.meta), ("", "")


def _edu_lines(sec: Section) -> tuple[tuple[str, str], tuple[str, str], list[str]]:
    """School with dates; degree with the grade on the right; the rest (coursework) below."""
    import re

    parts = [x.strip() for d in sec.details for x in re.split(r"(?<=\d)\.\s+(?=[A-Z])|;\s+|\s+\|\s+|(?<!Relevant)\s+(?=(?:Relevant\s+)?Coursework\s*:)", d) if x.strip()]
    grade = next((d for d in parts if len(d) <= 40 and re.search(r"c?gpa|percentage|%|cpi|sgpa|\d\s*/\s*10", d, re.I)), "")
    rest = [d for d in parts if d != grade]
    school, degree = (sec.sub, sec.heading) if sec.sub else (sec.heading, "")
    return (school, sec.meta), (degree, grade), rest


def _project_bullet(sec: Section) -> tuple[str, str]:
    """(bold name, the rest): "Name (2025): what it does. Python, Flask"."""
    body = " ".join(b.strip() for b in sec.bullets if b.strip())
    if sec.tech:
        body = f"{body.rstrip('.')}{'.' if body else ''} {sec.tech}".strip()
    return sec.heading, body


def render_pdf(doc: TailoredDoc) -> bytes:
    """A4, one column, real text. A role, project or degree never splits across pages; headings never sit alone at
    the bottom of a page."""
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

    ink, muted = colors.HexColor("#111111"), colors.HexColor("#444444")
    st = {
        "name": ParagraphStyle("name", fontName="Helvetica-Bold", fontSize=20, leading=24, alignment=TA_CENTER, textColor=ink),
        "contact": ParagraphStyle("contact", fontName="Helvetica", fontSize=9, leading=12, alignment=TA_CENTER, textColor=muted),
        "h": ParagraphStyle("h", fontName="Helvetica-Bold", fontSize=11.5, leading=14, textColor=ink, spaceBefore=8, spaceAfter=1, keepWithNext=1),
        "body": ParagraphStyle("body", fontName="Helvetica", fontSize=9.4, leading=12.2, textColor=ink),
        "role": ParagraphStyle("role", fontName="Helvetica-Bold", fontSize=9.8, leading=12, textColor=ink, spaceBefore=3, keepWithNext=1),
    }
    width = A4[0] - 30 * mm

    class TwoSide(Flowable):
        """Left text and right text on one line (plain text, no table), e.g. "Adobe, Bangalore ...... Mar 2021 - Present"."""

        def __init__(self, left: str, right: str, font: str, size: float, rfont: str | None = None, space: float = 2.5):
            super().__init__()
            self.left, self.right, self.font, self.size = pdf_safe(left), pdf_safe(right), font, size
            self.rfont, self.space = rfont or font, space

        def wrap(self, aw, ah):
            self.aw = aw  # the frame's real width (narrower than the page minus margins)
            return aw, self.size + self.space + 1.5

        def draw(self):
            c = self.canv
            c.setFillColor(ink)
            c.setFont(self.font, self.size)
            c.drawString(0, 2, self.left)
            if self.right:
                c.setFont(self.rfont, self.size - 0.4)
                c.drawRightString(getattr(self, "aw", width), 2, self.right)

    def two(left: str, right: str, font: str, size: float, rfont: str | None = None, space: float = 2.5) -> list:
        if stringWidth(pdf_safe(left), font, size) + stringWidth(pdf_safe(right), rfont or font, size) + 12 <= width:
            f = TwoSide(left, right, font, size, rfont, space)
            f.keepWithNext = 1
            return [f]
        p = Paragraph(f'<font name="{font}">{esc(left)}</font>' + (f"  ·  {esc(right)}" if right else ""), ParagraphStyle("x", parent=st["body"], fontSize=size, keepWithNext=1))
        return [p]

    buf = io.BytesIO()
    pdf = SimpleDocTemplate(buf, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=12 * mm, bottomMargin=12 * mm, title=" — ".join(x for x in (doc.name, doc.target) if x), author=doc.name)
    story: list = [Paragraph(esc(doc.name), st["name"]), Spacer(1, 2), Paragraph(esc(doc.contact), st["contact"]), Spacer(1, 2)]

    def heading(text: str) -> list:
        rule = HRFlowable(width="100%", thickness=0.7, color=ink, spaceBefore=0, spaceAfter=3)
        rule.keepWithNext = 1
        return [Paragraph(esc(text), st["h"]), rule]

    def section(text: str, blocks: list[list]) -> None:
        """A heading always travels with its first entry, so it's never stranded at the bottom of a page."""
        if not blocks:
            return
        story.append(KeepTogether([*heading(text), *blocks[0]]))
        for b in blocks[1:]:
            story.append(KeepTogether(b))

    def bullet_list(items: list[str], rich: bool = False):
        return ListFlowable(
            [ListItem(Paragraph(b if rich else esc(b), st["body"]), leftIndent=11) for b in items],
            bulletType="bullet", start="•", leftIndent=11, bulletFontSize=8,
        )

    if doc.summary:
        section("Summary", [[Paragraph(esc(doc.summary), st["body"])]])
    if lines := _skill_lines(doc):
        section("Skills", [[Paragraph(f"<b>{esc(label)}:</b> {esc(items)}", st["body"]) for label, items in lines]])
    for part in _order(doc):
        if part == "Experience" and doc.experience:
            blocks = []
            for sec in doc.experience:
                (l1, r1), (l2, _) = _role_lines(sec)
                block = [Spacer(1, 2), *two(l1, r1, "Helvetica-Bold", 9.8, "Helvetica")]
                if l2:
                    block += two(l2, "", "Helvetica-Oblique", 9.4)
                items = list(sec.bullets) + ([sec.tech] if sec.tech else [])
                if items:
                    block.append(bullet_list(items))
                blocks.append(block)
            section(HEADING["Experience"], blocks)
        elif part == "Education" and doc.education_items:
            blocks = []
            for sec in doc.education_items:
                (l1, r1), (l2, r2), rest = _edu_lines(sec)
                block = [Spacer(1, 2), *two(l1, r1, "Helvetica-Bold", 9.8, "Helvetica")]
                if l2 or r2:
                    block += two(l2, r2, "Helvetica-Oblique", 9.4, "Helvetica")
                block += [Paragraph(esc(d), st["body"]) for d in rest]
                blocks.append(block)
            section("Education", blocks)
        elif part == "Projects" and doc.projects:
            blocks = []
            for sec in doc.projects:
                name, body = _project_bullet(sec)
                blocks.append([bullet_list([f"<b>{esc(name)}</b>{': ' + esc(body) if body else ''}"], rich=True)])
            section(HEADING["Projects"], blocks)
    if doc.additional:
        section("Additional Experience", [[bullet_list(doc.additional)]])
    if doc.certifications:
        section("Awards and Certificates", [[bullet_list(doc.certifications)]])
    pdf.build(story)
    return buf.getvalue()


def render_docx(doc: TailoredDoc) -> bytes:
    """The same layout in Word: A4, one column, right tab stop for dates, headings kept with their content, and a
    role or project never split across pages."""
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Mm, Pt, RGBColor

    d = Document()
    sec = d.sections[0]
    sec.page_width, sec.page_height = Mm(210), Mm(297)
    sec.left_margin = sec.right_margin = Mm(15)
    sec.top_margin = sec.bottom_margin = Mm(12)
    text_width = sec.page_width - sec.left_margin - sec.right_margin
    d.core_properties.title = " — ".join(x for x in (doc.name, doc.target) if x)
    d.core_properties.author = doc.name

    normal = d.styles["Normal"]
    normal.font.name = "Calibri"
    normal.font.size = Pt(10)
    normal.element.rPr.rFonts.set(qn("w:eastAsia"), "Calibri")
    pf = normal.paragraph_format
    pf.space_before, pf.space_after, pf.line_spacing = Pt(0), Pt(1), 1.0
    lb = d.styles["List Bullet"].paragraph_format
    lb.space_before, lb.space_after, lb.line_spacing = Pt(0), Pt(1), 1.0
    ink, muted = RGBColor(0x11, 0x11, 0x11), RGBColor(0x44, 0x44, 0x44)

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
        for k, v in (("w:val", "single"), ("w:sz", "6"), ("w:space", "1"), ("w:color", "111111")):
            bottom.set(qn(k), v)
        bdr.append(bottom)
        ppr.append(bdr)

    def heading(text: str) -> None:
        rule_below(para(text, bold=True, size=11.5, color=ink, before=8, after=2, keep=True))

    def two(left: str, right: str, *, bold=False, italic=False, before=0.0, keep=True) -> None:
        p = para(before=before, after=0, keep=keep)
        p.paragraph_format.tab_stops.add_tab_stop(text_width, WD_TAB_ALIGNMENT.RIGHT)
        r = p.add_run(left)
        r.bold, r.italic = bold, italic
        if right:
            m = p.add_run(f"\t{right}")
            m.font.size = Pt(9.5)

    def bullets(items: list, keep_last: bool = False) -> None:
        for i, b in enumerate(items):
            p = d.add_paragraph(style="List Bullet")
            if isinstance(b, tuple):  # (bold lead, rest)
                p.add_run(b[0]).bold = True
                if b[1]:
                    p.add_run(f": {b[1]}")
            else:
                p.add_run(b)
            p.paragraph_format.keep_together = True
            p.paragraph_format.keep_with_next = keep_last or i < len(items) - 1

    para(doc.name, bold=True, size=19, color=ink, align=WD_ALIGN_PARAGRAPH.CENTER, after=1)
    para(doc.contact, size=9, color=muted, align=WD_ALIGN_PARAGRAPH.CENTER, after=4)
    if doc.summary:
        heading("Summary")
        para(doc.summary)
    if lines := _skill_lines(doc):
        heading("Skills")
        for label, items in lines:
            p = para()
            p.add_run(f"{label}: ").bold = True
            p.add_run(items)
    for part in _order(doc):
        if part == "Experience" and doc.experience:
            heading(HEADING["Experience"])
            for s_ in doc.experience:
                (l1, r1), (l2, _) = _role_lines(s_)
                two(l1, r1, bold=True, before=3)
                if l2:
                    two(l2, "", italic=True)
                bullets(list(s_.bullets) + ([s_.tech] if s_.tech else []))
        elif part == "Education" and doc.education_items:
            heading("Education")
            for s_ in doc.education_items:
                (l1, r1), (l2, r2), rest = _edu_lines(s_)
                two(l1, r1, bold=True, before=3)
                if l2 or r2:
                    two(l2, r2, italic=True, keep=bool(rest))
                for i, det in enumerate(rest):
                    para(det, keep=i < len(rest) - 1)
        elif part == "Projects" and doc.projects:
            heading(HEADING["Projects"])
            bullets([_project_bullet(s_) for s_ in doc.projects])
    if doc.additional:
        heading("Additional Experience")
        bullets(doc.additional)
    if doc.certifications:
        heading("Awards and Certificates")
        bullets(doc.certifications)
    out = io.BytesIO()
    d.save(out)
    return out.getvalue()

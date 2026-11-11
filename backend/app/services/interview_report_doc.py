"""The downloadable mock-interview report (PDF and Word), in three parts, each starting on a new page:

1. Interviewer evaluation: candidate & job details, logistics, a 1-5 scoring matrix with comments (work experience &
   relevancy, education & technical skills, communication & interpersonal skills, problem-solving / cultural fit),
   round results, key strengths, concerns / red flags and a hiring recommendation, signed and dated.
2. Question-by-question review: every question asked, what it tested, your answer, its scores and feedback, and how to
   answer it (steps, points to mention, what to avoid, a sample answer; the verified solution for coding questions).
3. Candidate self-assessment: header, timing & logistics, questions asked / answered well / to improve, and the
   follow-up checklist (thank-you note, decision timeline, follow-up date) with space for your own notes.

It's a practice report: never shared with employers.
"""

import io
import textwrap
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.services.interview_report import COMPONENTS, GAP_TEXT
from app.services.resume_doc import pdf_safe

IST = ZoneInfo("Asia/Kolkata")
INTERVIEWERS = {"female": ("Ananya", "Senior recruiter"), "male": ("Arjun", "Hiring manager")}
RECOMMENDATION = {
    "Strong hire": "Strong Hire",
    "Hire": "Hire",
    "Lean no": "No Hire",
    "No hire": "Strong No Hire",
    "Ended early": "No Hire (interview ended early)",
    "Not enough answers": "No decision (too few answers)",
}
VERBAL_ROUNDS_EXPERIENCE = {"screening", "project", "proof", "skill", "portfolio", "behavioural"}
CRITERIA = [
    ("experience", "Work Experience & Relevancy", "How well your examples matched what this role needs."),
    ("technical", "Education & Technical Skills", "Depth in the field's core knowledge and, where asked, coding."),
    ("communication", "Communication & Interpersonal Skills", "Clear, structured answers; explaining your thinking."),
    ("problem", "Problem-Solving / Cultural Fit", "Reasoning through problems, cases and real situations."),
]


def _avg(xs: list[float]) -> float | None:
    xs = [x for x in xs if isinstance(x, (int, float))]
    return round(sum(xs) / len(xs), 1) if xs else None


def _when(s) -> datetime:
    started = (s.meta or {}).get("started_at")
    t = datetime.fromisoformat(started) if started else s.created_at
    return t.astimezone(IST)


def _matrix(s, round_kind: dict[int, str], bar: float) -> list[dict]:
    exp, tech, comm, prob = [], [], [], []
    for q in s.questions:
        sc = (s.scores or {}).get(q["id"])
        if not sc or sc.get("integrity_flags"):
            continue
        kind = round_kind.get(q.get("round"), "technical")
        if q.get("kind") == "coding" or kind == "coding":
            tech.append(sc.get("score"))
            comm.append(sc.get("communication"))
            prob += [sc.get("correctness"), sc.get("efficiency")]
            continue
        if kind in VERBAL_ROUNDS_EXPERIENCE or q.get("kind") in ("skill", "proof", "screening"):
            exp.append(sc.get("relevance"))
        if kind in ("technical", "case", "portfolio") or q.get("kind") in ("skill", "trend"):
            tech.append(sc.get("score"))
        comm.append(sc.get("structure"))
        if kind in ("case", "roleplay", "behavioural") or q.get("kind") == "situational":
            prob.append(sc.get("score"))
    if not exp:  # every interview has some answers that show fit; fall back to relevance overall
        exp = [v.get("relevance") for v in (s.scores or {}).values() if "relevance" in v]
    if not prob:
        prob = [v.get("score") for v in (s.scores or {}).values()]
    values = {"experience": _avg(exp), "technical": _avg(tech), "communication": _avg(comm), "problem": _avg(prob)}
    gap_for = {"experience": "relevance", "technical": "correctness", "communication": "structure", "problem": "efficiency"}
    rows = []
    for key, label, what in CRITERIA:
        v = values[key]
        if v is None:
            rows.append({"key": key, "label": label, "score": None, "comment": "Not assessed in this interview."})
            continue
        score = max(1, min(5, round(v)))
        if v >= bar + 0.5:
            comment = f"Strong ({v}/5, above the {bar}/5 bar). {what}"
        elif v >= bar:
            comment = f"Meets the bar ({v}/5). {what}"
        else:
            comment = f"Below the {bar}/5 bar ({v}/5). {GAP_TEXT[gap_for[key]] if key != 'technical' else 'Revise the core topics this role tests and practise explaining them with an example.'}"
        rows.append({"key": key, "label": label, "score": score, "avg": v, "comment": comment})
    return rows


def _steps(items: list[str]) -> list[str]:
    """The AI sometimes returns its three steps as one "1. … 2. … 3. …" string."""
    import re

    out = []
    for it in items:
        parts = [p.strip() for p in re.split(r"(?:^|\s)\d[.)]\s+", it) if p.strip()]
        out += parts if len(parts) > 1 else [it.strip()]
    return [x for x in out if x]


def compose(s, report: dict, guides: dict[str, dict], candidate: str) -> dict:
    """Everything the PDF and Word files print, in order."""
    meta = s.meta or {}
    job = meta.get("job") or {}
    when = _when(s)
    name, role = INTERVIEWERS.get(meta.get("interviewer", "female"), INTERVIEWERS["female"])
    round_kind = {r["index"]: r["kind"] for r in meta.get("rounds", [])}
    round_name = {r["index"]: r["name"] for r in meta.get("rounds", [])}
    integ = s.integrity or {}
    bar = report.get("bar", 3.2)
    ended = s.completed_at.astimezone(IST) if s.completed_at else None

    questions = []
    for n, q in enumerate(s.questions, 1):
        sc = (s.scores or {}).get(q["id"]) or {}
        kind = "coding" if q.get("kind") == "coding" else "verbal"
        answer = (s.answers or {}).get(q["id"], "")
        approach = ""
        if kind == "coding" and "/* Approach:" in answer:
            answer, approach = answer.split("/* Approach:", 1)
            approach = approach.rsplit("*/", 1)[0].strip()
        problem = q.get("problem") or {}
        questions.append(
            {
                "n": n,
                "id": q["id"],
                "round": q.get("round_name") or round_name.get(q.get("round"), ""),
                "kind": kind,
                "question": f"{problem.get('title')}: {problem.get('statement')}" if kind == "coding" and problem else q["q"],
                "tests": (guides.get(q["id"]) or {}).get("tests") or q.get("jd_line", ""),
                "answer": answer.strip(),
                "approach": approach,
                "language": sc.get("language", ""),
                "score": sc.get("score"),
                "components": [(label, sc.get(key)) for key, label in COMPONENTS[kind].items() if sc.get(key) is not None],
                "verdict": f"{sc.get('verdict', '')} · {sc.get('tests_label', '')}".strip(" ·") if kind == "coding" and sc else "",
                "feedback": [f for f in (sc.get("improvements") or sc.get("feedback") or []) if f][:4],
                "flagged": bool(sc.get("integrity_flags")),
                "guide": guides.get(q["id"]) or {},
            }
        )

    scored = [q for q in questions if q["score"] is not None and not q["flagged"]]
    well = [q for q in scored if q["score"] >= 4]
    weak = [q for q in scored if q["score"] < 3]
    strengths = [st for r in report["rounds"] for st in (f"{r['name']}: {x}" for x in r["strengths"])][:5]
    strengths += [f"Q{q['n']} ({q['round']}): scored {q['score']}/5" for q in well[: max(0, 4 - len(strengths))]]
    concerns = list(dict.fromkeys(g for r in report["rounds"] for g in r["gaps"]))[:6]
    if integ.get("violations"):
        concerns.append(f"{integ['violations']} integrity warning(s) in strict mode (left the window, paste blocked, etc.).")
    if (s.status or "") == "terminated":
        concerns.insert(0, "The interview was ended early for integrity reasons.")

    follow_up = (ended or when) + timedelta(days=7)
    return {
        "title": "Mock Interview Report",
        "candidate": candidate or "Candidate",
        "position": job.get("title", ""),
        "company": job.get("company", ""),
        "department": report.get("industry_name", ""),
        "interviewer": f"{name}, {role} (JobPilot AI interviewer)",
        "date": when.strftime("%d %b %Y"),
        "time": when.strftime("%I:%M %p IST").lstrip("0"),
        "format": f"Video call · AI mock interview · {report.get('level', 'intern').title()} level · {meta.get('minutes', '')} min planned"
        + (" · strict mode" if meta.get("strict") else ""),
        "duration": f"{report.get('minutes_used')} min" if report.get("minutes_used") is not None else "—",
        "arrival": f"Started on time at {when.strftime('%I:%M %p').lstrip('0')}",
        "status": {"completed": "Completed", "terminated": "Ended early (integrity)", "active": "Not finished"}.get(s.status or "active", s.status or ""),
        "overall": report.get("score"),
        "bar": bar,
        "signal": report.get("signal", ""),
        "recommendation": RECOMMENDATION.get(report.get("signal", ""), report.get("signal", "")),
        "summary": report.get("summary") or "",
        "matrix": _matrix(s, round_kind, bar),
        "rounds": report["rounds"],
        "strengths": strengths or ["Not enough strong answers yet to name a clear strength."],
        "concerns": concerns or ["No significant concerns."],
        "next_week": _steps(report.get("next_week") or [f["do"] for f in report.get("focus", [])]),
        "questions": questions,
        "self": {
            "asked": [f"Q{q['n']}. {q['question'][:150]}" + ("…" if len(q["question"]) > 150 else "") for q in questions],
            "well": [f"Q{q['n']} ({q['round']}, {q['score']}/5): {q['question'][:110]}" for q in well] or ["None scored 4/5 or above this time."],
            "improve": [f"Q{q['n']} ({q['round']}, {q['score']}/5): {(q['feedback'] or q['guide'].get('approach') or [''])[0]}" for q in weak]
            + [f"Q{q['n']}: not answered" for q in questions if q["score"] is None][:4]
            or ["No answer scored below 3/5."],
            "follow_up_date": follow_up.strftime("%d %b %Y"),
        },
        "signed": f"JobPilot AI interview panel · {datetime.now(IST).strftime('%d %b %Y')}",
    }


def filename(data: dict, ext: str) -> str:
    import re

    stem = re.sub(r"[^A-Za-z0-9]+", "_", f"Interview report {data['candidate']} {data['company']} {data['date']}").strip("_")[:100]
    return f"{stem}.{ext}"


def _score(v) -> str:
    return "—" if v is None else f"{v}/5"


# ---------- PDF ----------


def render_pdf(data: dict) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import CondPageBreak, HRFlowable, KeepTogether, ListFlowable, ListItem, PageBreak, Paragraph, Preformatted, SimpleDocTemplate, Spacer, Table, TableStyle
    from xml.sax.saxutils import escape as _esc

    def esc(t) -> str:
        return _esc(pdf_safe(str(t)))

    ink, muted, accent, line, soft = colors.HexColor("#14141C"), colors.HexColor("#5A5A6A"), colors.HexColor("#2F3A8F"), colors.HexColor("#D5D7E3"), colors.HexColor("#F3F4F9")
    st = {
        "title": ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=19, leading=23, textColor=ink, spaceAfter=2),
        "sub": ParagraphStyle("sub", fontName="Helvetica", fontSize=9.5, leading=13, textColor=muted, spaceAfter=8),
        "part": ParagraphStyle("part", fontName="Helvetica-Bold", fontSize=14, leading=18, textColor=accent, spaceAfter=4),
        "h": ParagraphStyle("h", fontName="Helvetica-Bold", fontSize=10.5, leading=14, textColor=accent, spaceBefore=9, spaceAfter=3, keepWithNext=1),
        "q": ParagraphStyle("q", fontName="Helvetica-Bold", fontSize=10, leading=13.5, textColor=ink, spaceBefore=2, spaceAfter=3),
        "label": ParagraphStyle("label", fontName="Helvetica-Bold", fontSize=8.6, leading=11.5, textColor=muted, spaceBefore=4, spaceAfter=1, keepWithNext=1),
        "body": ParagraphStyle("body", fontName="Helvetica", fontSize=9.2, leading=12.6, textColor=ink),
        "small": ParagraphStyle("small", fontName="Helvetica", fontSize=8.4, leading=11, textColor=muted),
        "cell": ParagraphStyle("cell", fontName="Helvetica", fontSize=8.8, leading=11.5, textColor=ink),
        "cellb": ParagraphStyle("cellb", fontName="Helvetica-Bold", fontSize=8.8, leading=11.5, textColor=ink),
        "code": ParagraphStyle("code", fontName="Courier", fontSize=7.8, leading=9.6, textColor=ink, backColor=soft, borderPadding=4, leftIndent=4, rightIndent=4, spaceBefore=2, spaceAfter=4),
        "rec": ParagraphStyle("rec", fontName="Helvetica-Bold", fontSize=12, leading=16, textColor=accent),
    }
    width = A4[0] - 32 * mm

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(muted)
        canvas.drawString(16 * mm, 8 * mm, pdf_safe(f"{data['candidate']} · {data['position']} · {data['company']} · practice report, not shared with employers"))
        canvas.drawRightString(A4[0] - 16 * mm, 8 * mm, f"Page {doc.page}")
        canvas.restoreState()

    def table(rows, widths, header=True, label_col=False):
        t = Table(rows, colWidths=widths, repeatRows=1 if header else 0)
        style = [
            ("GRID", (0, 0), (-1, -1), 0.5, line),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 3.5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
        ]
        if header:
            style.append(("BACKGROUND", (0, 0), (-1, 0), soft))
        if label_col:
            style.append(("BACKGROUND", (0, 0), (0, -1), soft))
        t.setStyle(TableStyle(style))
        return t

    def P(t, s="cell"):
        return Paragraph(esc(t), st[s])

    def bullets(items, style="body"):
        return ListFlowable([ListItem(Paragraph(esc(b), st[style]), leftIndent=10) for b in items], bulletType="bullet", start="•", leftIndent=10, bulletFontSize=8)

    def heading(t):
        rule = HRFlowable(width="100%", thickness=0.6, color=line, spaceBefore=0, spaceAfter=4)
        rule.keepWithNext = 1
        return [Paragraph(esc(t).upper(), st["h"]), rule]

    def details_table():
        rows = [
            [P("Candidate", "cellb"), P(data["candidate"]), P("Date & time", "cellb"), P(f"{data['date']}, {data['time']}")],
            [P("Position", "cellb"), P(data["position"]), P("Company", "cellb"), P(data["company"])],
            [P("Department / field", "cellb"), P(data["department"]), P("Interviewer", "cellb"), P(data["interviewer"])],
        ]
        return table(rows, [width * 0.17, width * 0.33, width * 0.17, width * 0.33], header=False)

    story: list = []
    # ----- Part 1: interviewer evaluation -----
    story += [Paragraph(esc(data["title"]), st["title"]), Paragraph(esc(f"{data['position']} · {data['company']} · {data['date']}"), st["sub"])]
    story += [Paragraph("Part 1 · Interviewer evaluation", st["part"])]
    story += heading("Candidate & job details") + [details_table()]
    story += heading("Timing & logistics")
    story.append(
        table(
            [
                [P("Arrival", "cellb"), P(data["arrival"]), P("Format", "cellb"), P(data["format"])],
                [P("Time used", "cellb"), P(data["duration"]), P("Status", "cellb"), P(data["status"])],
            ],
            [width * 0.17, width * 0.33, width * 0.17, width * 0.33],
            header=False,
        )
    )
    story += heading("Scoring matrix (1 = poor, 5 = excellent)")
    rows = [[P("Criterion", "cellb"), P("Score", "cellb"), P("Comments", "cellb")]]
    rows += [[P(m["label"], "cellb"), P(_score(m["score"])), P(m["comment"])] for m in data["matrix"]]
    rows.append([P("Overall", "cellb"), P(_score(data["overall"]), "cellb"), P(f"Average of all answers. The bar for this level is {data['bar']}/5.")])
    story.append(table(rows, [width * 0.30, width * 0.10, width * 0.60]))
    story += heading("Round results")
    rows = [[P("Round", "cellb"), P("Score", "cellb"), P("Bar", "cellb"), P("Result", "cellb"), P("Answered", "cellb")]]
    rows += [[P(r["name"]), P(_score(r["score"])), P(f"{r['bar']}/5"), P(r["status"]), P(f"{r['answered']} of {r['total']}")] for r in data["rounds"]]
    story.append(table(rows, [width * 0.40, width * 0.13, width * 0.12, width * 0.20, width * 0.15]))
    story += heading("Summary & recommendation")
    if data["summary"]:
        story.append(Paragraph(esc(data["summary"]), st["body"]))
    story.append(KeepTogether([Paragraph("Key strengths", st["label"]), bullets(data["strengths"])]))
    story.append(KeepTogether([Paragraph("Concerns / red flags", st["label"]), bullets(data["concerns"])]))
    story.append(
        KeepTogether(
            [
                Spacer(1, 6),
                table(
                    [[P("Hiring recommendation", "cellb"), Paragraph(esc(data["recommendation"]), st["rec"])], [P("Signature & date", "cellb"), P(data["signed"])]],
                    [width * 0.30, width * 0.70],
                    header=False,
                    label_col=True,
                ),
                Paragraph("Scale: Strong Hire · Hire · No Hire · Strong No Hire. Practice signal against the bar for your level; not shared with any employer.", st["small"]),
            ]
        )
    )
    if data["next_week"]:
        story += heading("Practice plan for the next 7 days") + [bullets(data["next_week"])]
    for r in data["rounds"]:
        if r["gaps"] or r["improvements"]:
            block = [Paragraph(esc(f"{r['name']} · {_score(r['score'])} · {r['status']}"), st["label"])]
            if r.get("norm"):
                block.append(Paragraph(esc(f"What this round expects: {r['norm']}"), st["small"]))
            items = [*(f"Gap: {g}" for g in r["gaps"][:3]), *(f"Do: {i}" for i in r["improvements"][:3])]
            block.append(bullets(items))
            if r is data["rounds"][0]:
                story += heading("Round by round: gaps and what to do")
            story.append(KeepTogether(block))

    # ----- Part 2: every question and how to answer it -----
    story.append(PageBreak())
    story += [Paragraph("Part 2 · Every question, and how to answer it", st["part"]), Paragraph(esc(f"{len(data['questions'])} questions, in the order they were asked. Each shows your answer and score, then how a strong answer is built."), st["sub"])]
    last_round = None
    for q in data["questions"]:
        if q["round"] != last_round:
            if last_round is not None:
                story.append(CondPageBreak(90 * mm))  # a new round starts on a new page unless there's plenty of room
            story += heading(q["round"] or "Questions")
            last_round = q["round"]
        g = q["guide"]
        # The question, what it tests and your answer stay on one page when they fit.
        head = [Paragraph(esc(f"Q{q['n']}. {q['question']}"), st["q"])]
        if q["tests"]:
            head.append(Paragraph(esc(f"What it tests: {q['tests']}"), st["small"]))
        head.append(Paragraph("Your answer", st["label"]))
        if not q["answer"]:
            head.append(Paragraph("Not answered.", st["body"]))
        elif q["kind"] == "coding":
            if q["approach"]:
                head.append(Paragraph(esc(f"Approach you wrote: {q['approach']}"), st["body"]))
            head.append(Preformatted("\n".join(textwrap.fill(ln, 104, subsequent_indent="    ", replace_whitespace=False) if len(ln) > 104 else ln for ln in pdf_safe(q["answer"]).splitlines()) or " ", st["code"]))
        else:
            head.append(Paragraph(esc(q["answer"]).replace("\n", "<br/>"), st["body"]))
        if q["score"] is not None or q["flagged"]:
            parts = [f"{label} {v}/5" for label, v in q["components"]]
            line_ = ("Not counted (integrity). " if q["flagged"] else f"Score {q['score']}/5") + (" · " + " · ".join(parts) if parts else "") + (f" · {q['verdict']}" if q["verdict"] else "")
            head.append(Paragraph(esc(line_), st["small"]))
        story.append(KeepTogether(head))
        if q["feedback"]:
            story.append(KeepTogether([Paragraph("Feedback", st["label"]), bullets(q["feedback"])]))
        how = [Paragraph("How to answer it", st["label"])]
        if g.get("approach"):
            how.append(ListFlowable([ListItem(Paragraph(esc(a), st["body"]), leftIndent=12) for a in g["approach"]], bulletType="1", leftIndent=12, bulletFontSize=8.5))
        story.append(KeepTogether(how))
        if g.get("mention"):
            story.append(KeepTogether([Paragraph("Make sure to mention", st["label"]), bullets(g["mention"])]))
        if g.get("avoid"):
            story.append(KeepTogether([Paragraph("Avoid", st["label"]), bullets(g["avoid"])]))
        if g.get("sample"):
            story.append(KeepTogether([Paragraph("Sample answer" + (" (fill in the [brackets] with your real details)" if "[" in g["sample"] and q["kind"] != "coding" else ""), st["label"]), Paragraph(esc(g["sample"]), st["body"])]))
        if g.get("code"):
            story += [Paragraph("Sample solution (Python, passes every test)", st["label"]), Preformatted(pdf_safe(g["code"]), st["code"])]
        story.append(Spacer(1, 6))
        story.append(HRFlowable(width="100%", thickness=0.3, color=line, spaceBefore=2, spaceAfter=6))

    # ----- Part 3: candidate self-assessment -----
    story.append(PageBreak())
    self_ = data["self"]
    story += [Paragraph("Part 3 · Candidate self-assessment", st["part"]), Paragraph("Your reflection on this interview. Fill in the blanks after a real interview too.", st["sub"])]
    story += heading("Header") + [details_table()]
    story += heading("Timing & logistics")
    story.append(table([[P("Arrival status", "cellb"), P(data["arrival"])], [P("Format", "cellb"), P(data["format"])], [P("Time used", "cellb"), P(data["duration"])]], [width * 0.25, width * 0.75], header=False, label_col=True))
    story += heading("Content & question review")
    story += [Paragraph("Key questions asked", st["label"]), bullets(self_["asked"], "small")]
    story += [Paragraph("Questions I answered well", st["label"]), bullets(self_["well"])]
    story += [Paragraph("Areas for improvement", st["label"]), bullets(self_["improve"])]
    story.append(Paragraph("In my own words, what I'd do differently: ______________________________________________", st["body"]))
    story += heading("Follow-up & next steps")
    story.append(
        table(
            [
                [P("Item", "cellb"), P("Status", "cellb"), P("Notes", "cellb")],
                [P("Thank-you note sent"), P("[  ] Yes   [  ] No"), P("Send within 24 hours of a real interview; mention one thing you discussed.")],
                [P("Agreed decision timeline"), P("[  ] Asked"), P("Ask at the end: “What are the next steps, and by when should I expect to hear?”")],
                [P("Follow-up date"), P(self_["follow_up_date"]), P("If you haven't heard by then, send a short, polite follow-up.")],
                [P("Practice before next interview"), P("[  ] Done"), P("; ".join(data["next_week"][:2]) or "Redo the weakest round in JobPilot.")],
            ],
            [width * 0.27, width * 0.18, width * 0.55],
        )
    )
    buf = io.BytesIO()
    pdf = SimpleDocTemplate(buf, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm, topMargin=14 * mm, bottomMargin=16 * mm, title=pdf_safe(f"{data['title']} — {data['candidate']}"), author="JobPilot")
    pdf.build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()


# ---------- Word ----------


def render_docx(data: dict) -> bytes:
    from docx import Document
    from docx.enum.table import WD_TABLE_ALIGNMENT
    from docx.enum.text import WD_BREAK
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Mm, Pt, RGBColor

    d = Document()
    sec = d.sections[0]
    sec.page_width, sec.page_height = Mm(210), Mm(297)
    sec.left_margin = sec.right_margin = Mm(16)
    sec.top_margin, sec.bottom_margin = Mm(14), Mm(16)
    d.core_properties.title = f"{data['title']} — {data['candidate']}"
    d.core_properties.author = "JobPilot"
    normal = d.styles["Normal"]
    normal.font.name, normal.font.size = "Calibri", Pt(10)
    normal.element.rPr.rFonts.set(qn("w:eastAsia"), "Calibri")
    normal.paragraph_format.space_after, normal.paragraph_format.line_spacing = Pt(2), 1.05
    ink, muted, accent = RGBColor(0x14, 0x14, 0x1C), RGBColor(0x5A, 0x5A, 0x6A), RGBColor(0x2F, 0x3A, 0x8F)

    foot = sec.footer.paragraphs[0]
    r = foot.add_run(f"{data['candidate']} · {data['position']} · {data['company']} · practice report, not shared with employers")
    r.font.size, r.font.color.rgb = Pt(7.5), muted

    def para(text="", *, bold=False, italic=False, size=None, color=None, before=None, after=None, keep=False, style=None):
        p = d.add_paragraph(style=style) if style else d.add_paragraph()
        if text:
            run = p.add_run(text)
            run.bold, run.italic = bold, italic
            if size:
                run.font.size = Pt(size)
            if color is not None:
                run.font.color.rgb = color
        if before is not None:
            p.paragraph_format.space_before = Pt(before)
        if after is not None:
            p.paragraph_format.space_after = Pt(after)
        p.paragraph_format.keep_with_next = keep
        return p

    def rule_below(p):
        ppr = p._p.get_or_add_pPr()
        bdr = OxmlElement("w:pBdr")
        bottom = OxmlElement("w:bottom")
        for k, v in (("w:val", "single"), ("w:sz", "4"), ("w:space", "1"), ("w:color", "D5D7E3")):
            bottom.set(qn(k), v)
        bdr.append(bottom)
        ppr.append(bdr)

    def heading(t):
        rule_below(para(t.upper(), bold=True, size=10.5, color=accent, before=9, after=3, keep=True))

    def label(t):
        para(t, bold=True, size=9, color=muted, before=4, after=1, keep=True)

    def bullets(items, numbered=False):
        for b in items:
            p = d.add_paragraph(b, style="List Number" if numbered else "List Bullet")
            p.paragraph_format.space_after = Pt(1)
            p.paragraph_format.keep_together = True

    def shade(cell, hex_="F3F4F9"):
        tcpr = cell._tc.get_or_add_tcPr()
        shd = OxmlElement("w:shd")
        shd.set(qn("w:val"), "clear")
        shd.set(qn("w:color"), "auto")
        shd.set(qn("w:fill"), hex_)
        tcpr.append(shd)

    def table(rows, widths_mm, header=True, label_col=False, bold_cols=()):
        t = d.add_table(rows=len(rows), cols=len(rows[0]))
        t.style = "Table Grid"
        t.alignment = WD_TABLE_ALIGNMENT.CENTER
        for i, row in enumerate(rows):
            tr = t.rows[i]._tr
            trpr = tr.get_or_add_trPr()
            cant = OxmlElement("w:cantSplit")  # a row never splits across pages
            trpr.append(cant)
            if header and i == 0:
                th = OxmlElement("w:tblHeader")
                trpr.append(th)
            for j, val in enumerate(row):
                cell = t.cell(i, j)
                cell.width = Mm(widths_mm[j])
                cell.text = ""
                run = cell.paragraphs[0].add_run(str(val))
                run.font.size = Pt(9)
                run.bold = (header and i == 0) or (label_col and j == 0) or j in bold_cols
                if (header and i == 0) or (label_col and j == 0):
                    shade(cell)
        para(after=2)
        return t

    def page_break():
        d.add_paragraph().add_run().add_break(WD_BREAK.PAGE)

    def code(text):
        for ln in (text or " ").splitlines() or [" "]:
            p = para(after=0)
            p.paragraph_format.left_indent = Mm(3)
            p.paragraph_format.keep_together = True
            run = p.add_run(ln or " ")
            run.font.name, run.font.size = "Consolas", Pt(8)
            run.element.rPr.rFonts.set(qn("w:eastAsia"), "Consolas")
        para(after=3)

    details = [
        ["Candidate", data["candidate"], "Date & time", f"{data['date']}, {data['time']}"],
        ["Position", data["position"], "Company", data["company"]],
        ["Department / field", data["department"], "Interviewer", data["interviewer"]],
    ]

    # Part 1
    para(data["title"], bold=True, size=19, color=ink, after=0)
    para(f"{data['position']} · {data['company']} · {data['date']}", size=9.5, color=muted, after=8)
    para("Part 1 · Interviewer evaluation", bold=True, size=14, color=accent, after=4)
    heading("Candidate & job details")
    table(details, [30, 59, 30, 59], header=False, bold_cols=(0, 2))
    heading("Timing & logistics")
    table([["Arrival", data["arrival"], "Format", data["format"]], ["Time used", data["duration"], "Status", data["status"]]], [30, 59, 30, 59], header=False, bold_cols=(0, 2))
    heading("Scoring matrix (1 = poor, 5 = excellent)")
    rows = [["Criterion", "Score", "Comments"]] + [[m["label"], _score(m["score"]), m["comment"]] for m in data["matrix"]]
    rows.append(["Overall", _score(data["overall"]), f"Average of all answers. The bar for this level is {data['bar']}/5."])
    table(rows, [53, 18, 107], bold_cols=(0,))
    heading("Round results")
    table([["Round", "Score", "Bar", "Result", "Answered"]] + [[r["name"], _score(r["score"]), f"{r['bar']}/5", r["status"], f"{r['answered']} of {r['total']}"] for r in data["rounds"]], [70, 23, 21, 36, 28])
    heading("Summary & recommendation")
    if data["summary"]:
        para(data["summary"])
    label("Key strengths")
    bullets(data["strengths"])
    label("Concerns / red flags")
    bullets(data["concerns"])
    table([["Hiring recommendation", data["recommendation"]], ["Signature & date", data["signed"]]], [53, 125], header=False, label_col=True, bold_cols=(1,))
    para("Scale: Strong Hire · Hire · No Hire · Strong No Hire. Practice signal against the bar for your level; not shared with any employer.", size=8.5, color=muted)
    if data["next_week"]:
        heading("Practice plan for the next 7 days")
        bullets(data["next_week"])
    first = True
    for r in data["rounds"]:
        if r["gaps"] or r["improvements"]:
            if first:
                heading("Round by round: gaps and what to do")
                first = False
            label(f"{r['name']} · {_score(r['score'])} · {r['status']}")
            if r.get("norm"):
                para(f"What this round expects: {r['norm']}", size=8.5, color=muted, keep=True)
            bullets([*(f"Gap: {g}" for g in r["gaps"][:3]), *(f"Do: {i}" for i in r["improvements"][:3])])

    # Part 2
    page_break()
    para("Part 2 · Every question, and how to answer it", bold=True, size=14, color=accent, after=2)
    para(f"{len(data['questions'])} questions, in the order they were asked. Each shows your answer and score, then how a strong answer is built.", size=9.5, color=muted, after=6)
    last_round = None
    for q in data["questions"]:
        if q["round"] != last_round:
            if last_round is not None:
                page_break()  # each round starts on a new page
            heading(q["round"] or "Questions")
            last_round = q["round"]
        g = q["guide"]
        para(f"Q{q['n']}. {q['question']}", bold=True, size=10, color=ink, before=4, after=2, keep=True)
        if q["tests"]:
            para(f"What it tests: {q['tests']}", size=8.5, color=muted, keep=True)
        label("Your answer")
        if not q["answer"]:
            para("Not answered.")
        elif q["kind"] == "coding":
            if q["approach"]:
                para(f"Approach you wrote: {q['approach']}")
            code(q["answer"])
        else:
            for chunk in q["answer"].split("\n"):
                if chunk.strip():
                    para(chunk)
        if q["score"] is not None or q["flagged"]:
            parts = [f"{lbl} {v}/5" for lbl, v in q["components"]]
            para(("Not counted (integrity). " if q["flagged"] else f"Score {q['score']}/5") + (" · " + " · ".join(parts) if parts else "") + (f" · {q['verdict']}" if q["verdict"] else ""), size=8.5, color=muted)
        if q["feedback"]:
            label("Feedback")
            bullets(q["feedback"])
        if g.get("approach"):
            label("How to answer it")
            bullets(g["approach"], numbered=True)
        if g.get("mention"):
            label("Make sure to mention")
            bullets(g["mention"])
        if g.get("avoid"):
            label("Avoid")
            bullets(g["avoid"])
        if g.get("sample"):
            label("Sample answer" + (" (fill in the [brackets] with your real details)" if "[" in g["sample"] and q["kind"] != "coding" else ""))
            para(g["sample"])
        if g.get("code"):
            label("Sample solution (Python, passes every test)")
            code(g["code"])
        rule_below(para(after=6))

    # Part 3
    page_break()
    s_ = data["self"]
    para("Part 3 · Candidate self-assessment", bold=True, size=14, color=accent, after=2)
    para("Your reflection on this interview. Fill in the blanks after a real interview too.", size=9.5, color=muted, after=6)
    heading("Header")
    table(details, [30, 59, 30, 59], header=False, bold_cols=(0, 2))
    heading("Timing & logistics")
    table([["Arrival status", data["arrival"]], ["Format", data["format"]], ["Time used", data["duration"]]], [45, 133], header=False, label_col=True)
    heading("Content & question review")
    label("Key questions asked")
    bullets(s_["asked"])
    label("Questions I answered well")
    bullets(s_["well"])
    label("Areas for improvement")
    bullets(s_["improve"])
    para("In my own words, what I'd do differently: ______________________________________________", before=4)
    heading("Follow-up & next steps")
    table(
        [
            ["Item", "Status", "Notes"],
            ["Thank-you note sent", "☐ Yes   ☐ No", "Send within 24 hours of a real interview; mention one thing you discussed."],
            ["Agreed decision timeline", "☐ Asked", "Ask at the end: “What are the next steps, and by when should I expect to hear?”"],
            ["Follow-up date", s_["follow_up_date"], "If you haven't heard by then, send a short, polite follow-up."],
            ["Practice before next interview", "☐ Done", "; ".join(data["next_week"][:2]) or "Redo the weakest round in JobPilot."],
        ],
        [48, 32, 98],
        bold_cols=(0,),
    )
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


__all__ = ["compose", "render_pdf", "render_docx", "filename", "GAP_TEXT"]

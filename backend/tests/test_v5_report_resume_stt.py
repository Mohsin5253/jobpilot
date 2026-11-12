"""Resume restructuring (offline layout parser, structure in the PDF/Word), the downloadable interview report with
answer guides, and the speech-to-text accuracy helpers."""

import io
from types import SimpleNamespace

from app.services import resume_doc
from app.services.resume_restructure import clean_text, layout_parse, tidy

MESSY = """Ashish Pratap Singh
ć ashish@example.com | Ħ +91 98765 43210
a github.com/ashish | ] linkedin.com/in/ashish
Skills
Languages: C/C++, Java, Python, SQL
Technologies & Tools: AWS, EC2, S3, Kafka, Kuber-
netes, Docker, ReactJS
Work Experience
Adobe, Bangalore Mar 2021 - Present
Computer Scientist
• Led the migration of Hive and Presto jobs from Qubole to AWS EMR, enhancing availability and significantly reducing
operational costs.
• Reduced the cost of the custom reports service by more than 80% by disabling reports with no usage.
• AWS, EC2, S3, EMR, Hive, Presto, Kafka, Docker
Amazon, Bangalore Sept 2019 - Mar 2021
Software Development Engineer
• Built a batch workflow plugin that saved $6MM in labelling cost for ML experiments, by auto labelling high confidence records.
• Java, Python, AWS Lambda, DynamoDB, T ensorFlow
Education
BITS Hyderabad Aug 2013 - Jun 2017
B.E. in Computer Science and Engineering CGPA: 7.96/10
Relevant Coursework: Operating Systems, Databases, Computer Networks
Project Work
• Word Lookup Dictionary (2015): Developed a desktop app for looking up English words. Implemented search of valid words using a Trie. Implemented spelling correction using edit distance. Python, BeautifulSoup.
Awards and Certificates
• Data Engineering Nanodegree on Udacity
• Mentor at Scaler Academy"""


def test_messy_pdf_text_is_repaired():
    text, fixes = clean_text(MESSY)
    assert "Kubernetes" in text and "Kuber-" not in text and "TensorFlow" in text
    assert "ć" not in text and "ashish@example.com | +91 98765 43210" in text
    assert "reducing operational costs." in text  # wrapped bullet rejoined
    assert fixes["split_words"] >= 2 and fixes["icons"] >= 2


def test_layout_parser_builds_a_proper_structure():
    r = tidy(layout_parse(clean_text(MESSY)[0]))
    assert r.name == "Ashish Pratap Singh" and r.email == "ashish@example.com" and "github.com/ashish" in r.links
    adobe, amazon = r.experience
    assert (adobe.title, adobe.organization, adobe.location, adobe.start, adobe.end) == ("Computer Scientist", "Adobe", "Bangalore", "Mar 2021", "Present")
    assert len(adobe.bullets) == 2 and "EMR" in adobe.tech and "EC2" in adobe.tech  # stack moved out of the bullets, kept as written
    assert amazon.title == "Software Development Engineer" and "TensorFlow" in amazon.tech
    assert [g.name for g in r.skill_groups] == ["Languages", "Technologies & Tools"] and "Kubernetes" in r.skill_groups[1].items
    (p,) = r.projects
    assert p.name == "Word Lookup Dictionary (2015)" and p.tech == ["Python", "BeautifulSoup"] and len(p.bullets) == 3
    (e,) = r.education
    assert e.school == "BITS Hyderabad" and e.degree.startswith("B.E.") and "CGPA: 7.96/10" in e.details and "Coursework" in e.details
    assert r.certifications == ["Data Engineering Nanodegree on Udacity", "Mentor at Scaler Academy"]


def test_structured_resume_renders_every_section():
    r = tidy(layout_parse(clean_text(MESSY)[0]))
    doc = resume_doc.build(r, None)
    assert doc.experience[0].title_line == "Computer Scientist — Adobe, Bangalore" and doc.experience[0].tech
    assert [n for n, _ in doc.skill_groups][:2] == ["Languages", "Technologies & Tools"]
    from pypdf import PdfReader

    text = "\n".join(pg.extract_text() for pg in PdfReader(io.BytesIO(resume_doc.render_pdf(doc))).pages)
    for want in ("Awards and Certificates", "Work Experience", "Project Work", "Mar 2021 – Present", "AWS, EC2", "Languages: C/C++", "CGPA: 7.96/10"):
        assert want in text, want
    # The sample's order: Skills, Work Experience, Education, Project Work, Awards and Certificates.
    assert text.index("Skills") < text.index("Work Experience") < text.index("Education") < text.index("Project Work") < text.index("Awards and Certificates")
    from docx import Document

    d = Document(io.BytesIO(resume_doc.render_docx(doc)))
    body = "\n".join(p.text for p in d.paragraphs)
    assert "Adobe, Bangalore\tMar 2021 – Present\nComputer Scientist" in body and "Data Engineering Nanodegree on Udacity" in body
    assert "Word Lookup Dictionary (2015): Developed a desktop app" in body  # a project is one bullet led by its name
    assert resume_doc.pdf_safe("hands‑on − x") == "hands-on - x"


async def test_restructure_endpoint_with_a_file(authed):
    r = await authed.post("/api/resume/restructure", files={"file": ("cv.txt", MESSY.encode(), "text/plain")})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["resume"]["experience"][0]["organization"] == "Adobe" and body["resume"]["summary"]  # a summary is added
    assert "Certifications & awards" in body["sections"] and any("split" in n for n in body["notes"])
    assert body["after"] >= body["before"]
    # Without a file and without a saved resume, it asks for one.
    assert (await authed.post("/api/resume/restructure")).status_code == 409


def test_sample_answers_keep_to_the_candidates_facts():
    from app.services.interview_answers import keep_to_facts

    facts = "Project: Campus Eats (Flask, PostgreSQL): served 200 students. Reduced checkout time by 30%."
    out, n = keep_to_facts("I am at XYZ University. I built Campus Eats with Flask and Celery, cutting latency from 3.5 to 2.4 seconds for 200 students (30%).", facts, {"Flask", "PostgreSQL"})
    assert "Celery" not in out and "XYZ" not in out and "3.5" not in out and "200 students" in out and "30%" in out and "Campus Eats" in out and n >= 4


async def test_interview_report_downloads_as_pdf_and_word(authed):
    from tests.test_interview_v3 import _match

    mid = await _match()
    s = (await authed.post("/api/interviews", json={"match_id": mid, "minutes": 30, "strict": False})).json()
    assert (await authed.get(f"/api/interviews/{s['id']}/report/download")).status_code == 409  # nothing answered yet
    for q in s["questions"]:
        if q["kind"] != "coding":
            await authed.post(f"/api/interviews/{s['id']}/answer", json={"question_id": q["id"], "answer": "I built Campus Eats in Python. I designed the API and it served 200 students, which cut queues by 30%."})
    pdf = await authed.get(f"/api/interviews/{s['id']}/report/download?format=pdf")
    assert pdf.status_code == 200 and pdf.headers["content-type"] == "application/pdf" and "Interview_report" in pdf.headers["content-disposition"]
    from pypdf import PdfReader

    pages = [p.extract_text() for p in PdfReader(io.BytesIO(pdf.content)).pages]
    text = "\n".join(pages)
    for want in ("Part 1 · Interviewer evaluation", "Work Experience & Relevancy", "Hiring recommendation", "Part 2 · Every question", "How to answer it", "Part 3 · Candidate self-assessment", "Thank-you note sent"):
        assert want in text, want
    assert next(i for i, p in enumerate(pages) if "Part 2" in p) > 0 and "Part 3" in pages[-1] and "Part 2" not in pages[-1]  # parts start on new pages
    coding = next(q for q in s["questions"] if q["kind"] == "coding")
    assert f"def {coding['problem']['fn']['python']}(" in text  # the verified sample solution
    docx = await authed.get(f"/api/interviews/{s['id']}/report/download?format=docx")
    from docx import Document

    d = Document(io.BytesIO(docx.content))
    body = "\n".join(p.text for p in d.paragraphs)
    assert "Part 3 · Candidate self-assessment" in body and "How to answer it" in body and len(d.tables) >= 5


def test_report_matrix_and_recommendation():
    from datetime import UTC, datetime

    from app.services import interview_report, interview_report_doc
    from app.services.interview_answers import rule_guide

    qs = [
        {"id": "q1", "kind": "screening", "q": "Tell me about yourself", "jd_line": "Intro", "key_points": ["degree"], "round": 0, "round_name": "Screening"},
        {"id": "q2", "kind": "technical", "q": "What is an index?", "jd_line": "SQL", "key_points": [], "round": 1, "round_name": "Technical"},
    ]
    s = SimpleNamespace(
        questions=qs, answers={"q1": "I study CS.", "q2": "A lookup structure."}, status="completed", created_at=datetime.now(UTC), completed_at=datetime.now(UTC), integrity={},
        scores={"q1": {"score": 4.7, "relevance": 5, "specificity": 4, "structure": 5, "feedback": []}, "q2": {"score": 2.0, "relevance": 2, "specificity": 2, "structure": 2, "feedback": ["Give an example."]}},
        meta={"rounds": [{"index": 0, "name": "Screening", "kind": "screening"}, {"index": 1, "name": "Technical", "kind": "technical"}], "level": "intern", "job": {"title": "SDE Intern", "company": "Acme"}, "interviewer": "male", "minutes": 30},
    )
    rep = interview_report.build(s)
    data = interview_report_doc.compose(s, rep, {q["id"]: rule_guide(q, "technical") for q in qs}, "Asha")
    labels = {m["label"]: m["score"] for m in data["matrix"]}
    assert labels["Work Experience & Relevancy"] == 5 and labels["Education & Technical Skills"] == 2
    assert data["recommendation"] in ("No Hire", "Strong No Hire", "Hire") and data["interviewer"].startswith("Arjun")
    assert data["self"]["well"][0].startswith("Q1") and data["self"]["improve"][0].startswith("Q2")
    assert interview_report_doc._steps(["1. Do A. 2. Do B. 3. Do C."]) == ["Do A.", "Do B.", "Do C."]


def test_speech_filters_silence_and_uses_spoken_style_prompt():
    from app.api.routes.speech import keep_speech, polish, prompt_for

    res = SimpleNamespace(
        text=" I built it. Thank you.",
        segments=[
            {"text": " I built it with Postgres cal.", "no_speech_prob": 0.01, "avg_logprob": -0.2, "compression_ratio": 1.2},
            {"text": " Thank you.", "no_speech_prob": 0.9, "avg_logprob": -1.2, "compression_ratio": 0.8},
        ],
    )
    assert polish(keep_speech(res)) == "I built it with PostgreSQL."
    assert keep_speech(SimpleNamespace(text=" .", segments=[])) == ""
    p = prompt_for("Tell me about Docker and cicd. Python, FastAPI")
    assert p.startswith("So, um,") and "Docker" in p and "FastAPI" in p and "Tell me about" not in p


def test_speech_spells_your_own_words():
    from app.schemas import EducationItem, ExperienceItem, ProjectItem, ResumeData
    from app.services.speech_vocab import correct, guard_ai_fix, personal_vocabulary, whisper_prompt

    r = ResumeData(
        name="Mohsin Sidhpurwala", skills=["Python", "Flask", "RAG"], experience=[ExperienceItem(title="ML Intern", organization="QSkill")],
        projects=[ProjectItem(name="AI Medical Assistant (2025)")], education=[EducationItem(school="Rizvi College of Engineering")],
    )
    vocab = personal_vocabulary(r, {}, ["LangGraph"], job="HackerRank")
    assert vocab[0] == "Mohsin Sidhpurwala" and "Rizvi College of Engineering" in vocab and "AI Medical Assistant" in vocab and "LangGraph" in vocab
    assert "Mohsin Sidhpurwala" in whisper_prompt(vocab, ["Python"])
    text, fixes = correct("Hi, I'm Mohsen Sethpurwala. I study at Rizavi College of Engineering, interned at Q skill and built an ai medical assistant with flask.", vocab)
    assert text == "Hi, I'm Mohsin Sidhpurwala. I study at Rizvi College of Engineering, interned at QSkill and built an AI Medical Assistant with Flask."
    assert {"heard": "Mohsen Sethpurwala", "fixed": "Mohsin Sidhpurwala"} in fixes
    # Correct text and ordinary words are left alone.
    ok = "I'm Mohsin Sidhpurwala from Rizvi College of Engineering. I like to rag on my friends."
    assert correct(ok, vocab) == (ok, [])
    # The AI pass may only swap in vocabulary words; a rephrase is rejected.
    assert guard_ai_fix("I built it with Flax", "I built it with Flask", vocab)
    assert not guard_ai_fix("I built it with Flax", "I developed it using Flask", vocab)


async def test_speech_words_are_saved(authed):
    r = await authed.put("/api/stt/words", json={"words": ["Sidhpurwala", " LangGraph ", "Sidhpurwala"]})
    assert r.json()["words"] == ["Sidhpurwala", "LangGraph"]
    assert (await authed.get("/api/stt/words")).json()["words"] == ["Sidhpurwala", "LangGraph"]


def test_ai_speech_fix_must_sound_like_what_was_heard():
    from app.services.speech_vocab import guard_ai_fix

    v = ["scikit-learn", "SQLite", "Flask"]
    assert guard_ai_fix("built with Sclite and", "built with SQLite and", v)
    assert not guard_ai_fix("built with Sclite and", "built with scikit-learn and", v)  # a different word, even if it's yours

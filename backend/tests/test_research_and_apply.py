"""Researcher discovery, new-match notifications, tailored resume documents and one-click send."""

import io
from pathlib import Path

import httpx
import respx
from docx import Document

from app.agents import researcher as researcher_mod
from app.config import settings
from app.services.runs import claim_next, enqueue_research_runs, execute_run

SAMPLE = Path(__file__).resolve().parents[1] / "evals" / "data" / "sample_resume.md"


async def _upload(c):
    r = await c.post("/api/profile/resume", files={"file": ("resume.md", SAMPLE.read_bytes(), "text/markdown")})
    assert r.status_code == 200


async def _work():
    claimed = await claim_next("test-worker")
    assert claimed is not None
    return await execute_run(claimed.id, claimed.user_id)


def test_slug_variants():
    assert researcher_mod.slug_variants("Acme Technologies Pvt Ltd") == ["acme"]
    assert researcher_mod.slug_variants("Urban Company") == ["urbancompany", "urban-company", "urban"]


@respx.mock
async def test_researcher_discovers_boards_and_notifies(authed, monkeypatch):
    monkeypatch.setattr(settings, "researcher_enabled", True)
    monkeypatch.setattr(researcher_mod, "CATALOG", ["Acme", "Ghost Co"])
    respx.get("https://boards-api.greenhouse.io/v1/boards/acme/jobs").mock(return_value=httpx.Response(200, json={"jobs": [
        {"id": 1, "title": "Data Analyst Intern", "location": {"name": "Bengaluru"}},
        {"id": 2, "title": "Senior Engineer", "location": {"name": "Pune"}},
    ]}))
    respx.get(url__regex=r"https://(boards-api\.greenhouse\.io|api\.lever\.co|api\.ashbyhq\.com)/.*").mock(return_value=httpx.Response(404))
    await _upload(authed)

    r = await authed.post("/api/research/run")
    assert r.status_code == 202 and r.json()["trigger"] == "research"
    assert (await authed.post("/api/research/run")).status_code == 409  # one run at a time
    await _work()

    prefs = (await authed.get("/api/profile")).json()["preferences"]
    assert "acme" in prefs["greenhouse_boards"]  # live board with a fitting role was added
    state = (await authed.get("/api/research")).json()
    assert state["added"][0]["token"] == "acme" and state["added"][0]["fits"] == 1 and state["checked"] >= 2
    notes = (await authed.get("/api/notifications")).json()
    assert any(n["kind"] == "research" and "Acme" in n["body"] for n in notes)
    assert any(n["kind"] == "new_match" for n in notes)  # demo feed produced fits too
    assert (await authed.get("/api/stats/overview")).json()["unread_notifications"] == len(notes)
    await authed.post("/api/notifications/read", json={})
    assert (await authed.get("/api/stats/overview")).json()["unread_notifications"] == 0


async def test_continuous_research_schedule(authed):
    await _upload(authed)
    assert await enqueue_research_runs() == 1  # never ran -> due
    assert await enqueue_research_runs() == 0  # just queued -> not due again
    await _work()
    assert await enqueue_research_runs() == 0  # ran within the interval


async def test_tailored_resume_documents(authed):
    await _upload(authed)
    await authed.post("/api/runs")
    await _work()
    m = next(x for x in (await authed.get("/api/matches")).json()["items"] if x["has_tailored"])
    pdf = await authed.get(f"/api/matches/{m['id']}/resume")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF") and "attachment" in pdf.headers["content-disposition"]
    docx = await authed.get(f"/api/matches/{m['id']}/resume", params={"format": "docx"})
    text = "\n".join(p.text for p in Document(io.BytesIO(docx.content)).paragraphs)
    assert "Relevant to this role:" in text and "Aarav Mehta" in text
    profile = (await authed.get("/api/profile")).json()
    for line in text.splitlines():  # nothing on the document outside the resume's own skill list
        if line.startswith("Relevant to this role:"):
            assert set(line.split(":", 1)[1].strip().split(", ")) <= set(profile["resume"]["skills"])


async def test_send_application_attaches_resume(authed, monkeypatch):
    sent: list[dict] = []

    async def fake_send(to, subject, body, *, sender, reply_to=None, attachments=None, cc=None):
        sent.append({"to": to, "subject": subject, "attachments": attachments, "cc": cc, "from": sender.from_email})

    async def fake_verify(sender):
        return None

    monkeypatch.setattr("app.services.mailer.send_email", fake_send)
    monkeypatch.setattr("app.api.routes.account.verify_login", fake_verify)
    # The service's own SMTP is configured, but applications must never go out through it.
    monkeypatch.setattr(settings, "smtp_host", "smtp.service.example")
    monkeypatch.setattr(settings, "smtp_from", "noreply@jobpilot.example")
    await _upload(authed)
    await authed.post("/api/runs")
    await _work()
    d = (await authed.get("/api/drafts")).json()[0]

    assert (await authed.post(f"/api/drafts/{d['id']}/send", json={})).status_code == 409  # no mailbox of their own yet
    r = await authed.put("/api/mail-account", json={"username": "aarav@gmail.com", "password": "abcd efgh ijkl mnop"})
    assert r.status_code == 200 and r.json()["connected"] and "password" not in r.text
    if not d["to_email"]:
        assert (await authed.post(f"/api/drafts/{d['id']}/send", json={})).status_code == 422
    r = await authed.post(f"/api/drafts/{d['id']}/send", json={"to_email": "hr@company.example"})
    assert r.status_code == 200 and r.json()["status"] == "sent"
    name, content, mime = sent[0]["attachments"][0]
    assert sent[0]["to"] == "hr@company.example" and mime == "application/pdf" and content.startswith(b"%PDF") and name.endswith(".pdf")
    assert sent[0]["from"] == "aarav@gmail.com"  # from the user's own address
    match = (await authed.get(f"/api/matches/{d['match_id']}")).json()
    assert match["stage"] == "applied"

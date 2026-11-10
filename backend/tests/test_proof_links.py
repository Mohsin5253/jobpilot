"""Step 5: signed Proof Links: issued on approval, tamper-evident, verifiable, revocable, opens in the Tracker."""

from sqlalchemy import select, update

from app.db import session_scope
from app.models import Consent, Job, JobMatch, Notification, OutreachDraft, Profile, ProofLink, ProofLinkView, User
from app.services import proof_links as pl


async def _approved(authed, publish: bool = True) -> tuple[str, str]:
    async with session_scope() as s:
        me = (await s.execute(select(User))).scalar_one()
        await s.execute(
            update(Profile).where(Profile.user_id == me.id).values(
                proof_slug="aarav-x1", evidence={"github": {"verified": True, "username": "aarav", "top_repos": []}, "codeforces": {"rating": 1624}},
                resume={"name": "Aarav Mehta"},
            )
        )
        if publish:
            s.add(Consent(user_id=me.id, purpose="public_proof", notice_version="2026-11"))
        j = Job(source="t", external_id="1", company="Acme AI", title="ML Intern", description="Python " * 80, legit_status="verified")
        s.add(j)
        await s.flush()
        m = JobMatch(user_id=me.id, job_id=j.id, score=85)
        s.add(m)
        await s.flush()
        d = OutreachDraft(user_id=me.id, match_id=m.id, to_email="hr@acme.example", subject="Hi", email_body="Hello\n\nProof of my work: http://localhost:3000/p/aarav-x1")
        s.add(d)
        await s.flush()
        draft_id, match_id = str(d.id), str(m.id)
    assert (await authed.post(f"/api/drafts/{draft_id}/decision", json={"decision": "approve"})).status_code == 200
    return draft_id, match_id


async def test_approval_issues_a_signed_link_that_recruiters_can_verify(authed, client):
    draft_id, match_id = await _approved(authed)
    links = (await authed.get("/api/proof-links")).json()
    assert len(links) == 1 and links[0]["company"] == "Acme AI"
    url = links[0]["url"]
    slug, token = url.split("/p/")[1].split("/")
    v = (await client.get(f"/api/v1/verify/{token}")).json()
    assert v["valid"] and v["payload"]["approved_by"] == "student" and v["payload"]["github_verified"] and v["payload"]["codeforces_rating"] == 1624
    assert pl.verify_signature(v["payload"], v["signature"], v["public_key"])
    # Independent check: a changed payload doesn't verify against the published key.
    assert not pl.verify_signature({**v["payload"], "company": "Google"}, v["signature"], v["public_key"])

    # Tampering with any character of the token fails.
    bad = token[:-1] + ("A" if token[-1] != "A" else "B")
    assert (await client.get(f"/api/v1/verify/{bad}")).json()["valid"] is False
    assert (await client.get(f"/api/public/proof-link/{slug}/{bad}")).status_code == 404
    assert (await client.get(f"/api/public/proof-link/other/{token}")).status_code == 404

    page = await client.get(f"/api/public/proof-link/{slug}/{token}", headers={"x-viewer-ua": "Mozilla/5.0 (iPhone) AppleWebKit Safari/604 Mobile"})
    assert page.status_code == 200 and page.json()["application"]["role"] == "ML Intern"
    await client.get(f"/api/public/proof-link/{slug}/{token}", headers={"x-viewer-ua": "WhatsApp/2.23 link preview"})  # a bot: logged, not counted
    tracker = (await authed.get("/api/matches", params={"stage": ["applied"]})).json()["items"]
    assert tracker[0]["proof_views"] == 1 and tracker[0]["proof_last_viewed_at"]
    async with session_scope() as s:
        fams = sorted(v.ua_family for v in (await s.execute(select(ProofLinkView))).scalars())
        assert fams == ["bot", "safari-mobile"]
        assert (await s.execute(select(Notification).where(Notification.kind == "proof_view"))).scalar_one()

    # The student can revoke it: the page and verification stop working.
    assert (await authed.post(f"/api/proof-links/{links[0]['id']}/revoke")).json()["revoked_at"]
    assert (await client.get(f"/api/public/proof-link/{slug}/{token}")).status_code == 404
    v = (await client.get(f"/api/v1/verify/{token}")).json()
    assert v["valid"] is False and v["revoked"] is True


async def test_sent_email_carries_the_signed_link(authed, monkeypatch):
    draft_id, _ = await _approved(authed)
    sent = {}

    async def fake_send(user_id, to, subject, body, **kw):
        sent["body"] = body

    monkeypatch.setattr("app.services.applications.send_as_user", fake_send)
    from app.services.applications import send_application

    await send_application(__import__("uuid").UUID(draft_id))
    async with session_scope() as s:
        link = (await s.execute(select(ProofLink))).scalar_one()
    assert f"/p/aarav-x1/{link.token}" in sent["body"] and sent["body"].count("/p/aarav-x1") == 1


async def test_no_link_without_a_published_proof_page(authed):
    await _approved(authed, publish=False)
    assert (await authed.get("/api/proof-links")).json() == []

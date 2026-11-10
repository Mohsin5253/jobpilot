"""Step 7: WhatsApp approvals (signed, idempotent, same checks as the web) and language preference."""

from datetime import UTC, datetime, timedelta

import httpx
import respx
from sqlalchemy import func, select, update

from app.config import settings
from app.db import session_scope
from app.models import ApprovalEvent, Consent, Job, JobMatch, OutreachDraft, Profile, User
from app.services import whatsapp as wa

NUMBER = "919876543210"


async def _setup(n_drafts: int = 1):
    async with session_scope() as s:
        me = (await s.execute(select(User))).scalar_one()
        await s.execute(update(Profile).where(Profile.user_id == me.id).values(whatsapp_number=NUMBER))
        s.add(Consent(user_id=me.id, purpose="whatsapp", notice_version="2026-11"))
        ids = []
        for i in range(n_drafts):
            j = Job(source="t", external_id=f"w{i}", company=f"Acme{i}", title="ML Intern", description="Python " * 80, legit_status="verified", ghost_score=5)
            s.add(j)
            await s.flush()
            m = JobMatch(user_id=me.id, job_id=j.id, score=88)
            s.add(m)
            await s.flush()
            d = OutreachDraft(user_id=me.id, match_id=m.id, to_email="hr@acme.example", subject="Hi", email_body="Hello")
            s.add(d)
            await s.flush()
            ids.append(str(d.id))
        return me, ids


def _hook(msg_id: str, payload: str, frm: str = NUMBER) -> dict:
    return {"entry": [{"changes": [{"value": {"messages": [{"id": msg_id, "from": frm, "type": "button", "button": {"payload": payload, "text": "Approve"}}]}}]}]}


async def test_whatsapp_approve_is_signed_idempotent_and_audited(authed):
    me, [draft] = await _setup()
    payload = wa.sign_action("approve", draft, me)
    assert await wa.handle_inbound(_hook("wamid.1", payload)) == 1
    assert await wa.handle_inbound(_hook("wamid.1", payload)) == 0  # Meta retried: handled once
    async with session_scope() as s:
        d = await s.get(OutreachDraft, draft)
        assert d.status == "approved" and d.approval_channel == "whatsapp"
        ev = (await s.execute(select(ApprovalEvent))).scalars().all()
        assert [(e.action, e.channel) for e in ev] == [("approve", "whatsapp")]


async def test_forged_expired_or_old_session_buttons_do_nothing(authed):
    me, [draft] = await _setup()
    good = wa.sign_action("approve", draft, me)
    forged = good[:-1] + ("0" if good[-1] != "0" else "1")
    old = wa.sign_action("approve", draft, me, now=datetime.now(UTC) - timedelta(hours=25))
    await wa.handle_inbound(_hook("wamid.a", forged))
    await wa.handle_inbound(_hook("wamid.b", old))
    await wa.handle_inbound(_hook("wamid.c", good, frm="919999999999"))  # someone else's number
    assert (await authed.post("/api/auth/logout-all")).status_code == 204  # "sign out everywhere" voids buttons
    await wa.handle_inbound(_hook("wamid.d", good))
    async with session_scope() as s:
        assert (await s.get(OutreachDraft, draft)).status == "pending"
        assert (await s.execute(select(func.count()).select_from(ApprovalEvent))).scalar_one() == 0


async def test_whatsapp_approvals_respect_the_daily_quota_and_skip_keeps_it(authed):
    me, drafts = await _setup(7)
    for i, d in enumerate(drafts[:6]):
        await wa.handle_inbound(_hook(f"wamid.q{i}", wa.sign_action("approve", d, me)))
    await wa.handle_inbound(_hook("wamid.skip", wa.sign_action("skip", drafts[6], me)))
    async with session_scope() as s:
        statuses = [(await s.get(OutreachDraft, d)).status for d in drafts]
    assert statuses.count("approved") == 5 and statuses.count("pending") == 2


@respx.mock
async def test_digest_sends_approval_buttons_in_the_users_language(authed, monkeypatch):
    for k, v in {"whatsapp_token": "t", "whatsapp_phone_number_id": "1", "whatsapp_approval_template": "jobpilot_approval", "whatsapp_template_langs": ["en", "hi"]}.items():
        monkeypatch.setattr(settings, k, v)
    me, _ = await _setup(2)
    assert (await authed.put("/api/account/language", json={"language": "hi"})).json()["language"] == "hi"
    calls = respx.post(f"{wa.GRAPH}/1/messages").mock(return_value=httpx.Response(200, json={"messages": [{"id": "x"}]}))
    async with session_scope() as s:
        p = (await s.execute(select(Profile))).scalar_one()
        user = await s.get(User, p.user_id)
        async with httpx.AsyncClient() as c:
            assert await wa.send_approval_items(c, s, p, user) == 2
    import json

    body = json.loads(calls.calls.last.request.content)
    assert body["template"]["name"] == "jobpilot_approval" and body["template"]["language"]["code"] == "hi"
    payloads = [c["parameters"][0]["payload"] for c in body["template"]["components"] if c["type"] == "button"]
    assert [p.split(":")[1] for p in payloads] == ["approve", "edit", "skip"]
    assert "नई" in wa.t("digest", "hi", n=2, items="x", url="u") and "नवीन" in wa.t("digest", "mr", n=2, items="x", url="u")

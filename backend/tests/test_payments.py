"""Step 8: Razorpay payments: hosted checkout, verified + idempotent webhooks, GST-ready invoices, cancel, expiry,
and the (flagged) outcome plan."""

import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx
from sqlalchemy import select, update

from app.config import settings
from app.db import session_scope
from app.models import Job, JobMatch, Notification, Payment, User
from app.services import payments as pay


@pytest.fixture
def razorpay(monkeypatch):
    for k, v in {"razorpay_key_id": "rzp_test_x", "razorpay_key_secret": "sec", "razorpay_webhook_secret": "whsec", "razorpay_pro_plan_id": "plan_123"}.items():
        monkeypatch.setattr(settings, k, v)


def _signed(event: dict) -> tuple[bytes, dict]:
    body = json.dumps(event).encode()
    return body, {"x-razorpay-signature": hmac.new(b"whsec", body, hashlib.sha256).hexdigest(), "x-razorpay-event-id": "evt_" + hashlib.md5(body).hexdigest(), "content-type": "application/json"}


async def test_payments_are_off_until_configured(authed):
    assert (await authed.get("/api/payments/config")).json()["enabled"] is False
    assert (await authed.post("/api/payments/checkout/week_pass")).status_code == 409


@respx.mock
async def test_week_pass_flow_with_verified_idempotent_webhook_and_invoice(authed, client, razorpay):
    respx.post(f"{pay.API}/payment_links").mock(return_value=httpx.Response(200, json={"id": "plink_1", "short_url": "https://rzp.io/i/abc"}))
    r = await authed.post("/api/payments/checkout/week_pass")
    assert r.json()["url"] == "https://rzp.io/i/abc"
    event = {"event": "payment_link.paid", "payload": {"payment_link": {"entity": {"id": "plink_1"}}, "payment": {"entity": {"id": "pay_9", "amount": 4900}}}}
    body, headers = _signed(event)
    assert (await client.post("/api/payments/webhook", content=body, headers={**headers, "x-razorpay-signature": "forged"})).status_code == 400
    assert (await client.post("/api/payments/webhook", content=body, headers=headers)).json()["result"] == "week_pass_paid"
    assert (await client.post("/api/payments/webhook", content=body, headers=headers)).json()["result"] == "duplicate"
    async with session_scope() as s:
        u = (await s.execute(select(User))).scalar_one()
        assert u.plan == "pro" and timedelta(days=6) < u.plan_expires_at - datetime.now(UTC) <= timedelta(days=7)
        p = (await s.execute(select(Payment))).scalar_one()
        assert p.status == "paid" and p.invoice_number.startswith("JP/") and p.invoice["type"] == "Receipt"
    pays = (await authed.get("/api/payments")).json()
    html = (await authed.get(f"/api/payments/{pays[0]['id']}/invoice")).text
    assert "₹49.00" in html and "GST not charged" in html


def test_gst_invoice_split():
    settings_gstin = settings.seller_gstin
    try:
        settings.seller_gstin = "27ABCDE1234F1Z5"
        inv = pay.invoice_for(Payment(plan="pro_monthly", amount_inr=199), User(name="A", email="a@x.in"), "JP/2026-27/00001", datetime.now(UTC))
        assert inv["type"] == "Tax invoice" and inv["taxable_paise"] + inv["cgst_paise"] + inv["sgst_paise"] == 19900
        assert abs(inv["taxable_paise"] * 0.18 - (inv["cgst_paise"] + inv["sgst_paise"])) <= 1
    finally:
        settings.seller_gstin = settings_gstin


@respx.mock
async def test_pro_subscription_cancel_in_two_clicks_and_expiry(authed, client, razorpay):
    respx.post(f"{pay.API}/subscriptions").mock(return_value=httpx.Response(200, json={"id": "sub_1", "short_url": "https://rzp.io/i/sub"}))
    cancel = respx.post(f"{pay.API}/subscriptions/sub_1/cancel").mock(return_value=httpx.Response(200, json={"id": "sub_1"}))
    assert (await authed.post("/api/payments/checkout/pro_monthly")).json()["url"] == "https://rzp.io/i/sub"
    assert (await authed.get("/api/payments/config")).json()["subscribed"] is False  # not until Razorpay confirms
    end = int((datetime.now(UTC) + timedelta(days=30)).timestamp())
    body, headers = _signed({"event": "subscription.charged", "payload": {"subscription": {"entity": {"id": "sub_1", "current_end": end}}, "payment": {"entity": {"id": "pay_s1"}}}})
    assert (await client.post("/api/payments/webhook", content=body, headers=headers)).json()["result"] == "pro_active"
    assert (await authed.get("/api/payments/config")).json()["subscribed"] is True
    r = (await authed.post("/api/payments/cancel")).json()  # click 2 (click 1 opens the confirm dialog)
    assert cancel.called and r["plan"] == "pro" and r["subscribed"] is False
    assert await pay.expire_plans(datetime.now(UTC) + timedelta(days=31)) == 1
    async with session_scope() as s:
        assert (await s.execute(select(User.plan))).scalar_one() == "free"


@respx.mock
async def test_outcome_plan_asks_only_on_first_interview_with_evidence(authed, razorpay, monkeypatch):
    monkeypatch.setattr(settings, "outcome_plan_enabled", True)
    respx.post(f"{pay.API}/payment_links").mock(return_value=httpx.Response(200, json={"id": "plink_o", "short_url": "https://rzp.io/i/o"}))
    assert (await authed.put("/api/payments/outcome-plan", json={"enabled": True})).json()["outcome_plan"] is True
    async with session_scope() as s:
        me = (await s.execute(select(User))).scalar_one()
        j = Job(source="t", external_id="o1", company="Acme", title="Intern")
        s.add(j)
        await s.flush()
        m = JobMatch(user_id=me.id, job_id=j.id, score=80, stage="applied")
        s.add(m)
        await s.flush()
        mid = m.id
    assert (await authed.patch(f"/api/matches/{mid}", json={"outcome": "interview"})).status_code == 200  # no evidence: no ask
    async with session_scope() as s:
        await s.execute(update(JobMatch).values(outcome="none"))
    await authed.patch(f"/api/matches/{mid}", json={"outcome": "interview", "interview_evidence": "Calendar invite from hr@acme.com"})
    async with session_scope() as s:
        assert (await s.execute(select(Payment).where(Payment.plan == "outcome"))).scalar_one().status == "created"  # asked, never charged
        assert (await s.execute(select(Notification).where(Notification.kind == "payment"))).scalar_one()


@respx.mock
async def test_upi_qr_payment_for_week_pass_and_pro_month(authed, client, razorpay):
    create = respx.post(f"{pay.API}/payments/qr_codes").mock(
        side_effect=[
            httpx.Response(200, json={"id": "qr_1", "image_url": "https://rzp.io/i/qr1"}),
            httpx.Response(200, json={"id": "qr_2", "image_url": "https://rzp.io/i/qr2"}),
        ]
    )
    respx.get("https://rzp.io/i/qr1").mock(return_value=httpx.Response(200, content=b"\x89PNG fake"))
    r = (await authed.post("/api/payments/qr/week_pass")).json()
    assert r["amount_inr"] == 49 and r["expires_in_s"] == 1200
    body = json.loads(create.calls.last.request.content)
    assert body["type"] == "upi_qr" and body["usage"] == "single_use" and body["fixed_amount"] and body["payment_amount"] == 4900
    img = await authed.get(r["image"])
    assert img.status_code == 200 and img.headers["content-type"] == "image/png"
    assert (await authed.get(f"/api/payments/qr/{r['payment_id']}/status")).json()["status"] == "created"
    assert (await authed.get(f"/api/payments/{r['payment_id']}/invoice")).status_code == 404  # not paid yet

    # A credit for the wrong amount is ignored.
    bad, h = _signed({"event": "qr_code.credited", "payload": {"qr_code": {"entity": {"id": "qr_1"}}, "payment": {"entity": {"id": "pay_x", "amount": 100}}}})
    assert (await client.post("/api/payments/webhook", content=bad, headers=h)).json()["result"] == "amount_mismatch"
    ok, h = _signed({"event": "qr_code.credited", "payload": {"qr_code": {"entity": {"id": "qr_1"}}, "payment": {"entity": {"id": "pay_q1", "amount": 4900}}}})
    assert (await client.post("/api/payments/webhook", content=ok, headers=h)).json()["result"] == "week_pass_paid"
    st = (await authed.get(f"/api/payments/qr/{r['payment_id']}/status")).json()
    assert st["status"] == "paid" and st["plan"] == "pro"

    r2 = (await authed.post("/api/payments/qr/pro_month")).json()
    assert r2["amount_inr"] == 199
    ok2, h2 = _signed({"event": "qr_code.credited", "payload": {"qr_code": {"entity": {"id": "qr_2"}}, "payment": {"entity": {"id": "pay_q2", "amount": 19900}}}})
    assert (await client.post("/api/payments/webhook", content=ok2, headers=h2)).json()["result"] == "pro_month_paid"
    async with session_scope() as s:
        u = (await s.execute(select(User))).scalar_one()
        assert timedelta(days=36) < u.plan_expires_at - datetime.now(UTC) <= timedelta(days=37)  # 7 + 30 days, stacked
    assert (await authed.post("/api/payments/qr/lifetime")).status_code == 404


async def test_admins_always_have_pro(authed):
    async with session_scope() as s:
        await s.execute(update(User).values(is_admin=True, plan="free"))
    assert (await authed.get("/api/auth/me")).json()["plan"] == "pro"


@respx.mock
async def test_year_pass_is_365_days_for_1999_and_never_renews(authed, client, razorpay):
    import json as _json

    link = respx.post(f"{pay.API}/payment_links").mock(return_value=httpx.Response(200, json={"id": "plink_y", "short_url": "https://rzp.io/i/year"}))
    cfg = (await authed.get("/api/payments/config")).json()
    assert cfg["prices"]["year_pass"] == 1999 and cfg["prices"]["week_pass"] == 49 and cfg["prices"]["pro_monthly"] == 199
    assert (await authed.post("/api/payments/checkout/year_pass")).json()["url"] == "https://rzp.io/i/year"
    assert _json.loads(link.calls.last.request.content)["amount"] == 199900
    body, headers = _signed({"event": "payment_link.paid", "payload": {"payment_link": {"entity": {"id": "plink_y"}}, "payment": {"entity": {"id": "pay_y", "amount": 199900}}}})
    assert (await client.post("/api/payments/webhook", content=body, headers=headers)).json()["result"] == "year_pass_paid"
    async with session_scope() as s:
        u = (await s.execute(select(User))).scalar_one()
        assert u.plan == "pro" and timedelta(days=364) < u.plan_expires_at - datetime.now(UTC) <= timedelta(days=365)
        assert u.razorpay_subscription_id is None  # a pass, not a subscription

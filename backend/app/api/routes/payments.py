"""Payments: start Pro or a Week Pass on Razorpay's hosted pages, cancel in two clicks, invoices, and the webhook."""

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import select

from app.api.deps import RealUserDep, SessionDep, UserDep
from app.config import settings
from app.models import Payment
from app.services import payments as pay
from app.services.ratelimit import hit

router = APIRouter(tags=["payments"])


@router.get("/payments/config")
async def config(user: UserDep) -> dict:
    return {
        "enabled": settings.payments_enabled,
        "prices": {
            "pro_monthly": settings.price_pro_inr, "week_pass": settings.price_week_pass_inr, "year_pass": settings.price_year_pass_inr,
            **({"outcome": settings.price_outcome_inr} if settings.outcome_plan_enabled else {}),
        },
        "plan": user.plan, "plan_expires_at": user.plan_expires_at.isoformat() if user.plan_expires_at else None,
        "subscribed": bool(user.razorpay_subscription_id), "outcome_plan": user.outcome_plan, "outcome_available": settings.outcome_plan_enabled,
    }


@router.post("/payments/checkout/{plan}")
async def checkout(plan: str, user: RealUserDep, session: SessionDep) -> dict:
    try:
        if plan == "pro_monthly":
            url = await pay.start_pro(session, user)
        elif plan in pay.QR_PLANS:  # one-time passes: week, one month, year (UPI, card, netbanking on Razorpay's page)
            url = await pay.payment_link(session, user, plan, pay.pass_price(plan), pay.QR_PLANS[plan][0])
        else:
            raise HTTPException(404, "Unknown plan")
    except pay.PaymentsOff as exc:
        raise HTTPException(409, str(exc)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(502, "Razorpay didn't respond. Try again in a minute.") from exc
    await session.commit()
    return {"url": url}


@router.post("/payments/qr/{plan}")
async def qr(plan: str, user: RealUserDep, session: SessionDep) -> dict:
    """Pay by scanning a UPI QR (GPay, PhonePe, Paytm, any UPI app). Week Pass, or one month of Pro without renewal."""
    if plan not in pay.QR_PLANS:
        raise HTTPException(404, "Unknown plan")
    try:
        p = await pay.qr_checkout(session, user, plan)
    except pay.PaymentsOff as exc:
        raise HTTPException(409, str(exc)) from exc
    except httpx.HTTPError as exc:
        detail = "Razorpay couldn't create a QR code. Use the payment page instead, or try again."
        if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 400:
            detail = "UPI QR payments aren't switched on for this Razorpay account yet. Use the payment page (Week Pass / Get Pro) instead."
        raise HTTPException(502, detail) from exc
    await session.commit()
    return {"payment_id": str(p.id), "amount_inr": p.amount_inr, "image": f"/api/payments/qr/{p.id}/image", "expires_in_s": int(pay.QR_TTL.total_seconds())}


@router.get("/payments/qr/{payment_id}/image")
async def qr_image(payment_id: str, user: UserDep, session: SessionDep) -> Response:
    p = await session.get(Payment, payment_id)
    if p is None or p.user_id != user.id or not (p.invoice or {}).get("qr_image_url"):
        raise HTTPException(404, "No such QR code")
    try:
        data = await pay.qr_image(p.invoice["qr_image_url"])
    except (httpx.HTTPError, pay.PaymentsOff) as exc:
        raise HTTPException(502, "Couldn't load the QR code") from exc
    return Response(data, media_type="image/png", headers={"cache-control": "private, max-age=900"})


@router.get("/payments/qr/{payment_id}/status")
async def qr_status(payment_id: str, user: UserDep, session: SessionDep) -> dict:
    p = await session.get(Payment, payment_id)
    if p is None or p.user_id != user.id:
        raise HTTPException(404, "No such payment")
    if p.status == "created":  # don't wait for the webhook: ask Razorpay whether this QR was paid
        await pay.sync_user(session, user, only=p)
        await session.commit()
    return {"status": p.status, "plan": user.plan, "plan_expires_at": user.plan_expires_at.isoformat() if user.plan_expires_at else None}


@router.post("/payments/sync")
async def sync(user: RealUserDep, session: SessionDep) -> dict:
    """Checks Razorpay for this student's recent checkouts and applies any that were paid (in case a webhook was
    missed). Called by the Billing and Settings pages and after returning from Razorpay."""
    await hit("payments_sync", str(user.id))
    changed = await pay.sync_user(session, user)
    await session.commit()
    return {"changed": changed, "plan": user.plan, "plan_expires_at": user.plan_expires_at.isoformat() if user.plan_expires_at else None, "subscribed": bool(user.razorpay_subscription_id)}


@router.post("/payments/cancel")
async def cancel(user: RealUserDep, session: SessionDep) -> dict:
    """Cancel anytime: Pro stays until the end of the period you paid for, then you're on Free. Nothing else renews."""
    try:
        await pay.cancel_pro(session, user)
    except pay.PaymentsOff as exc:
        raise HTTPException(409, str(exc)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(502, "Razorpay didn't respond. Try again in a minute.") from exc
    await session.commit()
    return {"plan": user.plan, "plan_expires_at": user.plan_expires_at.isoformat() if user.plan_expires_at else None, "subscribed": False}


class OutcomeIn(__import__("pydantic").BaseModel):
    enabled: bool


@router.put("/payments/outcome-plan")
async def outcome_plan(body: OutcomeIn, user: RealUserDep, session: SessionDep) -> dict:
    if not settings.outcome_plan_enabled:
        raise HTTPException(404, "The outcome plan isn't offered yet")
    user.outcome_plan = body.enabled
    await session.commit()
    return {"outcome_plan": user.outcome_plan}


@router.get("/payments")
async def my_payments(user: UserDep, session: SessionDep) -> list[dict]:
    rows = (await session.execute(select(Payment).where(Payment.user_id == user.id, Payment.status == "paid").order_by(Payment.paid_at.desc()))).scalars().all()
    return [{"id": str(p.id), "plan": p.plan, "amount_inr": p.amount_inr, "paid_at": p.paid_at.isoformat() if p.paid_at else None, "invoice_number": p.invoice_number} for p in rows]


@router.get("/payments/{payment_id}/invoice", response_class=HTMLResponse)
async def invoice(payment_id: str, user: UserDep, session: SessionDep) -> HTMLResponse:
    """A printable invoice (save as PDF from the browser)."""
    p = await session.get(Payment, payment_id)
    if p is None or p.user_id != user.id or p.status != "paid" or not p.invoice:
        raise HTTPException(404, "No such invoice")
    inv = p.invoice
    rupees = lambda paise: f"₹{paise / 100:,.2f}"  # noqa: E731
    from html import escape

    rows = (
        f"<tr><td>Taxable value</td><td>{rupees(inv['taxable_paise'])}</td></tr><tr><td>CGST 9%</td><td>{rupees(inv['cgst_paise'])}</td></tr>"
        f"<tr><td>SGST 9%</td><td>{rupees(inv['sgst_paise'])}</td></tr>"
        if inv.get("taxable_paise") is not None
        else f"<tr><td colspan=2>{escape(inv.get('note', ''))}</td></tr>"
    )
    seller = inv["seller"]
    html = f"""<!doctype html><html><head><meta charset="utf-8"><title>{escape(inv['type'])} {escape(inv['number'])}</title>
<style>body{{font-family:system-ui,sans-serif;max-width:640px;margin:40px auto;padding:0 16px;color:#111}}td{{padding:6px 0}}table{{width:100%}}td+td{{text-align:right}}</style></head>
<body><h1>{escape(inv['type'])}</h1><p>No. {escape(inv['number'])} · {escape(inv['date'])}</p>
<p><b>{escape(seller['name'])}</b><br>{escape(seller.get('address') or '')}{'<br>GSTIN ' + escape(seller['gstin']) if seller.get('gstin') else ''}</p>
<p>Billed to: {escape(inv['buyer']['name'] or '')} &lt;{escape(inv['buyer']['email'])}&gt;</p>
<table><tr><td>{escape(inv['description'])} (SAC {escape(inv['sac'])})</td><td>{rupees(inv['total_paise'])}</td></tr>{rows}
<tr><td><b>Total</b></td><td><b>{rupees(inv['total_paise'])}</b></td></tr></table>
<p style="color:#666;font-size:13px">Paid via Razorpay. Payment ID {escape(p.razorpay_id or '')}.</p></body></html>"""
    return HTMLResponse(html, headers={"cache-control": "private, no-store"})


@router.post("/payments/webhook", include_in_schema=False)
async def webhook(request: Request) -> dict:
    body = await request.body()
    if not pay.valid_signature(body, request.headers.get("x-razorpay-signature")):
        raise HTTPException(400, "Bad signature")
    event_id = request.headers.get("x-razorpay-event-id") or __import__("hashlib").sha256(body).hexdigest()
    return {"result": await pay.handle_webhook(__import__("json").loads(body), event_id)}

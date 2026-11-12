"""Payments (F12) through Razorpay's hosted pages: no card or UPI details ever touch JobPilot.

* Pro, monthly: a Razorpay Subscription (UPI AutoPay or card) on a ₹299/month plan made in the dashboard.
* Week Pass: a one-time Payment Link for 7 days of Pro, no renewal.
* "₹99 on first interview" (experimental, OUTCOME_PLAN_ENABLED): when the student records an interview with
  evidence, we send them a payment link. Nothing is ever charged automatically.

Plans change on verified webhooks (HMAC-SHA256 with RAZORPAY_WEBHOOK_SECRET), each event id at most once, and on
reconciliation (sync_user): when the student opens Billing or comes back from Razorpay, we ask Razorpay's API for the
status of their recent payments, so a missing or misconfigured webhook never leaves a paid student on Free. Both
paths are idempotent: a payment grants its days exactly once. Paid payments get a sequential, GST-ready invoice.
"""

import hashlib
import hmac
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import session_scope
from app.logging import log
from app.models import Notification, Payment, User
from app.safety import egress

API = "https://api.razorpay.com/v1"
IST = ZoneInfo("Asia/Kolkata")


class PaymentsOff(RuntimeError):
    pass


def _auth() -> tuple[str, str]:
    if not settings.payments_enabled:
        raise PaymentsOff("Payments aren't set up on this server yet")
    return settings.razorpay_key_id or "", settings.razorpay_key_secret or ""


async def _call(method: str, path: str, json: dict | None = None) -> dict:
    async with egress.client("razorpay", timeout=20, auth=_auth()) as c:
        r = await c.request(method, f"{API}{path}", json=json)
    if r.status_code >= 300:
        try:
            err = (r.json().get("error") or {})
        except ValueError:
            err = {}
        # Razorpay's error code, field and description name the problem; they carry no secrets or card data.
        log.warning("razorpay.error", path=path.strip("/").replace("/", "."), status=r.status_code, code=err.get("code"), field=err.get("field"), reason=str(err.get("description", ""))[:200])
        raise httpx.HTTPStatusError("Razorpay refused the request", request=r.request, response=r)
    return r.json()


def valid_signature(body: bytes, signature: str | None) -> bool:
    if not settings.razorpay_webhook_secret or not signature:
        return False
    expected = hmac.new(settings.razorpay_webhook_secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


async def start_pro(s: AsyncSession, user: User) -> str:
    """A Pro subscription; returns Razorpay's hosted page URL."""
    if not settings.razorpay_pro_plan_id:
        raise PaymentsOff("The Pro plan isn't configured yet")
    sub = await _call("POST", "/subscriptions", {"plan_id": settings.razorpay_pro_plan_id, "total_count": 120, "customer_notify": 1, "notes": {"user_id": str(user.id)}})
    # The student isn't "subscribed" until Razorpay confirms the mandate (subscription.activated / .charged).
    s.add(Payment(user_id=user.id, plan="pro_monthly", amount_inr=settings.price_pro_inr, razorpay_ref=sub["id"]))
    return sub["short_url"]


async def _subscriber(s: AsyncSession, sub_id: str | None) -> User | None:
    """The student a subscription belongs to: from an activated one, or from the checkout that created it."""
    if not sub_id:
        return None
    user = (await s.execute(select(User).where(User.razorpay_subscription_id == sub_id))).scalar_one_or_none()
    if user is None:
        uid = (await s.execute(select(Payment.user_id).where(Payment.razorpay_ref == sub_id, Payment.plan == "pro_monthly").limit(1))).scalar_one_or_none()
        user = await s.get(User, uid) if uid else None
    return user


async def payment_link(s: AsyncSession, user: User, plan: str, amount: int, description: str) -> str:
    link = await _call(
        "POST",
        "/payment_links",
        {
            "amount": amount * 100, "currency": "INR", "description": description, "reminder_enable": False,
            "customer": {"name": user.name or "", "email": user.email}, "notify": {"email": False, "sms": False},
            "callback_url": f"{settings.app_url.rstrip('/')}/settings?paid={plan}#plan", "callback_method": "get",
            "notes": {"user_id": str(user.id), "plan": plan},
        },
    )
    s.add(Payment(user_id=user.id, plan=plan, amount_inr=amount, razorpay_ref=link["id"]))
    return link["short_url"]


QR_TTL = timedelta(minutes=20)  # Razorpay allows 2 minutes to 2 hours
QR_PLANS = {
    "week_pass": ("JobPilot Week Pass: 7 days of Pro", 7),
    "pro_month": ("JobPilot Pro: 1 month, no auto-renewal", 30),
    "year_pass": ("JobPilot Year Pass: 365 days of Pro", 365),
}


def pass_price(plan: str) -> int:
    """₹ for the one-time passes (week, one month, year). Prices live in settings."""
    return {"week_pass": settings.price_week_pass_inr, "pro_month": settings.price_pro_inr, "year_pass": settings.price_year_pass_inr}[plan]


async def qr_checkout(s: AsyncSession, user: User, plan: str) -> Payment:
    """A single-use Razorpay UPI QR for a fixed amount: scan it with any UPI app. Closes after 20 minutes.
    Pro bought this way is one month that doesn't renew (UPI AutoPay needs the subscription page instead)."""
    amount = pass_price(plan)
    description, _ = QR_PLANS[plan]
    qr = await _call(
        "POST",
        "/payments/qr_codes",
        {
            "type": "upi_qr", "name": "JobPilot", "usage": "single_use", "fixed_amount": True, "payment_amount": amount * 100,
            "description": description, "close_by": int((datetime.now(UTC) + QR_TTL).timestamp()), "notes": {"user_id": str(user.id), "plan": plan},
        },
    )
    p = Payment(user_id=user.id, plan=plan, amount_inr=amount, razorpay_ref=qr["id"], invoice={"qr_image_url": qr["image_url"]})
    s.add(p)
    await s.flush()
    return p


async def qr_image(url: str) -> bytes:
    """The QR picture, fetched server-side so the page needn't load images from another origin."""
    if not url.startswith("https://"):
        raise PaymentsOff("No QR image")
    async with egress.client("razorpay", timeout=15, follow_redirects=True) as c:
        r = await c.get(url)
    r.raise_for_status()
    return r.content


async def cancel_pro(s: AsyncSession, user: User) -> None:
    """Cancels at the end of the paid period: Pro stays until plan_expires_at, then lapses to Free."""
    if user.razorpay_subscription_id:
        await _call("POST", f"/subscriptions/{user.razorpay_subscription_id}/cancel", {"cancel_at_cycle_end": 1})
    user.razorpay_subscription_id = None


def invoice_for(p: Payment, user: User, number: str, now: datetime) -> dict:
    """GST-ready: with a seller GSTIN, 18% GST inside the price (CGST + SGST for the seller's state, IGST otherwise;
    the buyer's state is taken as the seller's unless known); without one, a receipt with no GST."""
    total = p.amount_inr * 100  # paise
    inv = {
        "number": number, "date": now.astimezone(IST).date().isoformat(), "seller": {"name": settings.seller_name, "address": settings.seller_address, "gstin": settings.seller_gstin},
        "buyer": {"name": user.name, "email": user.email}, "description": {"pro_monthly": "JobPilot Pro, 1 month", "pro_month": "JobPilot Pro, 1 month (no renewal)", "week_pass": "JobPilot Week Pass, 7 days", "year_pass": "JobPilot Year Pass, 365 days", "outcome": "JobPilot outcome plan (first interview)"}[p.plan],
        "sac": "998431", "total_paise": total, "currency": "INR",
    }
    if settings.seller_gstin:
        taxable = round(total / 1.18)
        gst = total - taxable
        inv |= {"type": "Tax invoice", "taxable_paise": taxable, "cgst_paise": gst // 2, "sgst_paise": gst - gst // 2, "igst_paise": 0, "place_of_supply": settings.seller_state_code}
    else:
        inv |= {"type": "Receipt", "note": "GST not charged: the seller isn't GST-registered."}
    return inv


async def _mark_paid(s: AsyncSession, p: Payment, payment_id: str | None, now: datetime) -> bool:
    """Marks a payment paid with its invoice. False if it already was (so its days are never granted twice)."""
    if p.status == "paid":
        return False
    user = await s.get(User, p.user_id) if p.user_id else None
    p.status, p.razorpay_id, p.paid_at = "paid", payment_id, now
    seq = (await s.execute(text("SELECT nextval('invoice_seq')"))).scalar_one()
    fy = now.astimezone(IST).year if now.astimezone(IST).month >= 4 else now.astimezone(IST).year - 1
    p.invoice_number = f"JP/{fy}-{str(fy + 1)[-2:]}/{seq:05d}"
    if user:
        p.invoice = invoice_for(p, user, p.invoice_number, now)
    return True


def _grant(user: User, until: datetime) -> None:
    user.plan = "pro"
    user.plan_expires_at = max(until, user.plan_expires_at or until)


async def _grant_pass(s: AsyncSession, p: Payment, now: datetime) -> None:
    user = await s.get(User, p.user_id) if p.user_id else None
    if user and p.plan in QR_PLANS:  # every one-time pass: week, one month, year
        _grant(user, max(now, user.plan_expires_at or now) + timedelta(days=QR_PLANS[p.plan][1]))


async def sync_user(s: AsyncSession, user: User, now: datetime | None = None, only: Payment | None = None) -> list[str]:
    """Asks Razorpay about this student's unpaid checkouts from the last 3 days and applies any that were paid.
    Returns what changed. Safe to call often: it only reads from Razorpay, and grants are idempotent."""
    if not settings.payments_enabled:
        return []
    now = now or datetime.now(UTC)
    rows = [only] if only is not None else (
        await s.execute(select(Payment).where(Payment.user_id == user.id, Payment.status == "created", Payment.created_at >= now - timedelta(days=3)).order_by(Payment.created_at.desc()).limit(10))
    ).scalars().all()
    changed: list[str] = []
    for p in rows:
        ref = p.razorpay_ref or ""
        try:
            if ref.startswith("plink_"):
                link = await _call("GET", f"/payment_links/{ref}")
                if link.get("status") == "paid":
                    pay_id = next((x.get("payment_id") for x in link.get("payments") or [] if x.get("status") == "captured"), None)
                    if await _mark_paid(s, p, pay_id, now):
                        await _grant_pass(s, p, now)
                        changed.append(f"{p.plan}_paid")
            elif ref.startswith("qr_"):
                pays = (await _call("GET", f"/payments/qr_codes/{ref}/payments")).get("items") or []
                ok = next((x for x in pays if x.get("status") == "captured" and int(x.get("amount", 0)) == p.amount_inr * 100), None)
                if ok and await _mark_paid(s, p, ok.get("id"), now):
                    await _grant_pass(s, p, now)
                    changed.append(f"{p.plan}_paid")
            elif ref.startswith("sub_") and p.plan == "pro_monthly":
                sub = await _call("GET", f"/subscriptions/{ref}")
                if sub.get("status") in ("active", "authenticated") or int(sub.get("paid_count") or 0) > 0:
                    user.razorpay_subscription_id = ref
                    end = datetime.fromtimestamp(sub["current_end"], UTC) if sub.get("current_end") else now + timedelta(days=31)
                    _grant(user, end)
                    if int(sub.get("paid_count") or 0) > 0:
                        await _mark_paid(s, p, None, now)
                    changed.append("pro_active")
        except Exception as exc:  # a failed lookup must never break Billing; the webhook still applies it later
            log.warning("payments.sync_failed", ref_kind=ref.split("_")[0], error=type(exc).__name__)
    return changed


async def handle_webhook(event: dict, event_id: str) -> str:
    """Applies one verified Razorpay event; returns what happened. Each event id is applied once."""
    now = datetime.now(UTC)
    name = event.get("event", "")
    async with session_scope() as s:
        fresh = (await s.execute(text("INSERT INTO payment_events (id, event) VALUES (:i, :e) ON CONFLICT DO NOTHING RETURNING id"), {"i": event_id, "e": name})).first()
        if fresh is None:
            return "duplicate"
        payload = event.get("payload", {})
        if name == "payment_link.paid":
            link = payload.get("payment_link", {}).get("entity", {})
            pay = payload.get("payment", {}).get("entity", {})
            p = (await s.execute(select(Payment).where(Payment.razorpay_ref == link.get("id")))).scalar_one_or_none()
            if p is None:
                return "unknown"
            if await _mark_paid(s, p, pay.get("id"), now):
                await _grant_pass(s, p, now)
            return f"{p.plan}_paid"
        if name == "qr_code.credited":
            qr = payload.get("qr_code", {}).get("entity", {})
            pay = payload.get("payment", {}).get("entity", {})
            p = (await s.execute(select(Payment).where(Payment.razorpay_ref == qr.get("id")))).scalar_one_or_none()
            if p is None:
                return "unknown"
            if pay.get("amount") is not None and int(pay["amount"]) != p.amount_inr * 100:
                log.warning("razorpay.qr_amount_mismatch")
                return "amount_mismatch"
            if await _mark_paid(s, p, pay.get("id"), now):
                await _grant_pass(s, p, now)
            return f"{p.plan}_paid"
        if name in ("subscription.activated", "subscription.charged"):
            sub = payload.get("subscription", {}).get("entity", {})
            pay = payload.get("payment", {}).get("entity", {})
            user = await _subscriber(s, sub.get("id"))
            if user is None:
                return "unknown"
            user.razorpay_subscription_id = sub["id"]
            end = datetime.fromtimestamp(sub["current_end"], UTC) if sub.get("current_end") else now + timedelta(days=31)
            _grant(user, end)
            if name == "subscription.charged" and pay.get("id"):
                p = (await s.execute(select(Payment).where(Payment.razorpay_ref == sub["id"], Payment.status == "created"))).scalars().first()
                if p is None:  # renewals: one row per charge
                    p = Payment(user_id=user.id, plan="pro_monthly", amount_inr=settings.price_pro_inr, razorpay_ref=sub["id"])
                    s.add(p)
                    await s.flush()
                await _mark_paid(s, p, pay["id"], now)
            return "pro_active"
        if name in ("subscription.cancelled", "subscription.halted", "subscription.completed"):
            sub = payload.get("subscription", {}).get("entity", {})
            user = await _subscriber(s, sub.get("id"))
            if user and user.razorpay_subscription_id == sub.get("id"):
                user.razorpay_subscription_id = None  # Pro lasts until plan_expires_at
            return "pro_ending"
        if name == "payment.failed":
            return "failed"
    return "ignored"


async def expire_plans(now: datetime | None = None) -> int:
    """Hourly: paid Pro / Week Pass that ran out goes back to Free. Hand-granted Pro (no expiry) is untouched."""
    now = now or datetime.now(UTC)
    async with session_scope() as s:
        res = await s.execute(
            text("UPDATE users SET plan = 'free' WHERE plan = 'pro' AND plan_expires_at IS NOT NULL AND plan_expires_at < :now AND razorpay_subscription_id IS NULL"), {"now": now}
        )
        return res.rowcount or 0


async def outcome_interview(s: AsyncSession, user: User, company: str) -> str | None:
    """Experimental outcome plan: on the first interview recorded with evidence, ask (never charge) for ₹99."""
    if not (settings.outcome_plan_enabled and settings.payments_enabled and user.outcome_plan):
        return None
    already = (await s.execute(select(Payment.id).where(Payment.user_id == user.id, Payment.plan == "outcome"))).first()
    if already:
        return None
    url = await payment_link(s, user, "outcome", settings.price_outcome_inr, "JobPilot outcome plan: first interview")
    s.add(Notification(user_id=user.id, kind="payment", title=f"Congratulations on the {company} interview!", body=f"Your outcome plan is ₹{settings.price_outcome_inr}, only now that it worked. Pay when you're ready: {url}"))
    return url

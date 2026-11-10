"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarDays, CalendarRange, Check, Clock, CreditCard, QrCode, Sparkles, Zap } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button, buttonClass } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { Switch } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/misc";
import { api } from "@/lib/api";
import { useMe, useProInterest, useUsage } from "@/lib/queries";
import { cn } from "@/lib/utils";

export type PayConfig = {
  enabled: boolean;
  prices: Record<string, number>;
  plan: string;
  plan_expires_at: string | null;
  subscribed: boolean;
  outcome_plan: boolean;
  outcome_available: boolean;
};
type PaidRow = { id: string; plan: string; amount_inr: number; paid_at: string | null; invoice_number: string | null };
type QrStart = { payment_id: string; amount_inr: number; image: string; expires_in_s: number };

export const PLAN_NAME: Record<string, string> = {
  pro_monthly: "Pro monthly (auto-renew)",
  pro_month: "Pro, 1 month",
  week_pass: "Week Pass",
  year_pass: "Year Pass",
  outcome: "Outcome plan",
};
const QR_LABEL: Record<string, string> = { week_pass: "Week Pass, 7 days", pro_month: "Pro, 1 month", year_pass: "Year Pass, 365 days" };
const PAID_MSG: Record<string, string> = {
  week_pass: "Paid. Your Week Pass is on: 7 days of Pro.",
  pro_month: "Paid. Pro is on for a month.",
  year_pass: "Paid. Your Year Pass is on: 365 days of Pro.",
};

const PRO_FEATURES = [
  "Up to 50 approved sends a day (Free: up to 10)",
  "Mock interviews built from each job description",
  "Proof Link analytics: who opened your proof page",
  "Referral finder and alumni lookup",
  "Alerts every minute, and 20 on-demand runs a day",
  "10× the AI budget for scoring and tailoring",
];

export const inr = (n: number) => `₹${n.toLocaleString("en-IN")}`;
const fmtDate = (iso: string) => new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });

export function usePayConfig() {
  return useQuery({ queryKey: ["pay-config"], queryFn: () => api.get<PayConfig>("/payments/config") });
}

/** A single-use Razorpay UPI QR for a fixed amount, shown in place. Polls until Razorpay confirms the payment. */
function ScanToPay({ plan, onClose }: { plan: string; onClose: () => void }) {
  const qc = useQueryClient();
  const [qr, setQr] = useState<(QrStart & { until: number }) | null>(null);
  const [left, setLeft] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const started = useRef(false);

  const start = async () => {
    setError(null);
    setQr(null);
    try {
      const r = await api.post<QrStart>(`/payments/qr/${plan}`);
      setQr({ ...r, until: Date.now() + r.expires_in_s * 1000 });
      setLeft(r.expires_in_s);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn’t create the QR code");
    }
  };
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    start();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  useEffect(() => {
    if (!qr) return;
    const tick = setInterval(() => setLeft(Math.max(0, Math.round((qr.until - Date.now()) / 1000))), 1000);
    const poll = setInterval(async () => {
      try {
        const st = await api.get<{ status: string }>(`/payments/qr/${qr.payment_id}/status`);
        if (st.status === "paid") {
          toast.success(PAID_MSG[plan] ?? "Paid.");
          qc.invalidateQueries();
          onClose();
        }
      } catch {
        /* keep polling */
      }
    }, 3000);
    return () => {
      clearInterval(tick);
      clearInterval(poll);
    };
  }, [qr, plan, qc, onClose]);

  const expired = !!qr && left === 0;
  return (
    <div className="mt-3 flex flex-col items-center gap-3 rounded-[var(--radius-card)] border border-border bg-elevated p-4 text-center">
      <div className="text-[14px] font-semibold">
        Scan to pay {qr ? inr(qr.amount_inr) : ""} · {QR_LABEL[plan]}
      </div>
      {error ? (
        <p className="text-[13px] text-[var(--error)]">{error}</p>
      ) : !qr ? (
        <Skeleton className="size-[240px]" />
      ) : expired ? (
        <p className="text-[13px] text-muted">This QR code expired. Make a new one.</p>
      ) : (
        // Served from our own API (same origin): the page loads no third-party images.
        // eslint-disable-next-line @next/next/no-img-element
        <img src={qr.image} alt={`UPI QR code to pay ${inr(qr.amount_inr)}`} width={240} height={240} className="rounded-[var(--radius-control)] bg-white p-2" />
      )}
      {qr && !expired && (
        <p className="text-[12.5px] text-muted">
          Open Google Pay, PhonePe, Paytm, BHIM or any UPI app and scan. Waiting for payment… {Math.floor(left / 60)}:{String(left % 60).padStart(2, "0")} left.
        </p>
      )}
      <div className="flex gap-2">
        {(expired || error) && (
          <Button size="sm" variant="primary" onClick={start}>
            New QR code
          </Button>
        )}
        <Button size="sm" variant="ghost" onClick={onClose}>
          Close
        </Button>
      </div>
    </div>
  );
}

type Tier = {
  id: "week_pass" | "monthly" | "year_pass";
  name: string;
  icon: typeof Clock;
  price: number;
  per: string;
  length: string;
  renews: string;
  bestFor: string;
  perDay: string;
  badge?: string;
};

/** The plans page: Free vs Week Pass vs Monthly vs Year Pass, with UPI QR or Razorpay checkout for each. */
export function PlansAndPayments() {
  const qc = useQueryClient();
  const params = useSearchParams();
  const want = params.get("plan");
  const { data: me } = useMe();
  const { data: cfg } = usePayConfig();
  const { data: usage } = useUsage();
  const { data: paid } = useQuery({ queryKey: ["payments"], queryFn: () => api.get<PaidRow[]>("/payments") });
  const ask = useProInterest();
  const [busy, setBusy] = useState<string | null>(null);
  const [scan, setScan] = useState<string | null>(null);
  const [confirm, setConfirm] = useState(false);

  useEffect(() => {
    if (params.get("paid")) toast.success("Payment received. Your plan updates within a minute of Razorpay confirming it.");
    if (want) document.getElementById(`tier-${want === "pro" ? "monthly" : want}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [params, want]);

  if (!cfg || !me) return <Skeleton className="h-96" />;
  const p = cfg.prices;
  const tiers: Tier[] = [
    { id: "week_pass", name: "Week Pass", icon: Zap, price: p.week_pass, per: "once", length: "7 days of Pro", renews: "Never renews", bestFor: "A placement week or a deadline sprint", perDay: inr(Math.round(p.week_pass / 7)) },
    {
      id: "monthly", name: "Monthly", icon: CalendarDays, price: p.pro_monthly, per: "a month", length: "Pro every month", renews: "Renews monthly · cancel anytime (or pay one month by QR)",
      bestFor: "Steady applying through a semester", perDay: inr(Math.round((p.pro_monthly / 30) * 10) / 10), badge: "Most flexible",
    },
    {
      id: "year_pass", name: "Year Pass", icon: CalendarRange, price: p.year_pass, per: "once", length: "365 days of Pro", renews: "Never renews",
      bestFor: "The whole placement season", perDay: inr(Math.round((p.year_pass / 365) * 10) / 10),
      badge: `Best value · save ${inr(p.pro_monthly * 12 - p.year_pass)}`,
    },
  ];

  const checkout = async (plan: string) => {
    setBusy(plan);
    try {
      const { url } = await api.post<{ url: string }>(`/payments/checkout/${plan}`);
      window.location.assign(url);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Couldn’t start the payment");
      setBusy(null);
    }
  };
  const cancel = async () => {
    setBusy("cancel");
    try {
      await api.post("/payments/cancel");
      toast.success("Pro cancelled. It stays on until the end of the period you paid for.");
      qc.invalidateQueries({ queryKey: ["pay-config"] });
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Couldn’t cancel");
    } finally {
      setBusy(null);
      setConfirm(false);
    }
  };

  const isPro = cfg.plan === "pro";
  const until = cfg.plan_expires_at ? fmtDate(cfg.plan_expires_at) : null;
  const demo = me.is_demo;

  return (
    <div className="space-y-6">
      {/* Where you stand now */}
      <Card>
        <div className="flex flex-wrap items-center justify-between gap-3 p-5">
          <div>
            <div className="flex items-center gap-2 text-[15px] font-semibold">
              You’re on <Badge tone={isPro ? "accent" : "neutral"}>{isPro ? "Pro" : "Free"}</Badge>
            </div>
            <p className="mt-1 text-[13px] text-muted">
              {isPro
                ? until
                  ? cfg.subscribed
                    ? `Renews monthly. Next period ends ${until}.`
                    : `Pro until ${until}, then Free. Nothing renews.`
                  : "Pro with no end date."
                : `Free: up to ${usage?.limits.drafts_per_day ?? 10} tailored applications a day. Pick a plan below for more depth.`}
            </p>
          </div>
          {cfg.subscribed &&
            (confirm ? (
              <div className="flex flex-wrap items-center gap-2 text-[13px]">
                Cancel monthly Pro? You keep it until {until ?? "the end of this period"}.
                <Button size="sm" variant="danger" loading={busy === "cancel"} onClick={cancel}>
                  Yes, cancel
                </Button>
                <Button size="sm" variant="ghost" onClick={() => setConfirm(false)}>
                  Keep Pro
                </Button>
              </div>
            ) : (
              <Button size="sm" variant="ghost" onClick={() => setConfirm(true)}>
                Cancel monthly Pro
              </Button>
            ))}
        </div>
      </Card>

      {!cfg.enabled && (
        <Card>
          <div className="flex flex-wrap items-center justify-between gap-3 p-5">
            <p className="text-[13.5px] text-muted">Payments open soon. During the beta, Pro is free on request: we switch it on by hand.</p>
            {!demo && !isPro && (
              <Button variant="primary" onClick={() => ask.mutate()} loading={ask.isPending} disabled={usage?.pro_requested}>
                {usage?.pro_requested ? "Requested" : "Request Pro"}
              </Button>
            )}
          </div>
        </Card>
      )}

      {/* The three ways to get Pro */}
      <div className="grid gap-4 lg:grid-cols-3">
        {tiers.map((t) => {
          const highlighted = want === t.id || (want === "pro" && t.id === "monthly");
          const qrPlan = t.id === "monthly" ? "pro_month" : t.id;
          return (
            <div
              key={t.id}
              id={`tier-${t.id}`}
              className={cn(
                "card flex flex-col p-5",
                (t.id === "year_pass" || highlighted) && "border-[color-mix(in_oklab,var(--cobalt)_45%,transparent)] shadow-[0_0_0_1px_color-mix(in_oklab,var(--cobalt)_25%,transparent)]",
              )}
            >
              <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-2 text-[15px] font-semibold">
                  <t.icon className="size-4 text-cobalt-text" /> {t.name}
                </div>
                {t.badge && <Badge tone={t.id === "year_pass" ? "accent" : "outline"}>{t.badge}</Badge>}
              </div>
              <div className="mt-3 flex items-baseline gap-1.5">
                <span className="num text-[34px] leading-none font-semibold tracking-[-0.03em]">{inr(t.price)}</span>
                <span className="text-[13px] text-text-3">{t.per}</span>
              </div>
              <ul className="mt-4 space-y-2 text-[13.5px] text-text-2">
                <li className="flex gap-2">
                  <Check className="mt-0.5 size-4 shrink-0 text-cobalt-text" /> {t.length}
                </li>
                <li className="flex gap-2">
                  <Check className="mt-0.5 size-4 shrink-0 text-cobalt-text" /> {t.renews}
                </li>
                <li className="flex gap-2">
                  <Check className="mt-0.5 size-4 shrink-0 text-cobalt-text" /> About {t.perDay} a day
                </li>
                <li className="flex gap-2">
                  <Sparkles className="mt-0.5 size-4 shrink-0 text-cobalt-text" /> Best for: {t.bestFor}
                </li>
              </ul>
              {cfg.enabled && !demo && (
                <div className="mt-auto space-y-2 pt-5">
                  {t.id === "monthly" ? (
                    <>
                      <Button variant="primary" className="w-full" loading={busy === "pro_monthly"} disabled={cfg.subscribed} onClick={() => checkout("pro_monthly")}>
                        <CreditCard /> {cfg.subscribed ? "You’re subscribed" : `Subscribe ${inr(t.price)}/month`}
                      </Button>
                      <Button className="w-full" onClick={() => setScan(scan === qrPlan ? null : qrPlan)}>
                        <QrCode /> Pay 1 month by UPI QR (no renewal)
                      </Button>
                    </>
                  ) : (
                    <>
                      <Button variant={t.id === "year_pass" ? "primary" : "secondary"} className="w-full" onClick={() => setScan(scan === qrPlan ? null : qrPlan)}>
                        <QrCode /> Pay {inr(t.price)} by UPI QR
                      </Button>
                      <Button className="w-full" variant="ghost" loading={busy === t.id} onClick={() => checkout(t.id)}>
                        <CreditCard /> Card, UPI ID or netbanking
                      </Button>
                    </>
                  )}
                  {scan === qrPlan && <ScanToPay plan={qrPlan} onClose={() => setScan(null)} />}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Side by side */}
      <Card>
        <CardHeader title="Week vs month vs year" description="Same Pro features in every option. Only the length and the way you pay differ." />
        <div className="overflow-x-auto px-5 pb-5">
          <table className="w-full min-w-[560px] text-left text-[13.5px]">
            <caption className="sr-only">Comparison of Week Pass, Monthly and Year Pass</caption>
            <thead className="text-[12.5px] text-text-3">
              <tr className="border-b border-border">
                <th scope="col" className="py-2 pr-3 font-medium" />
                {tiers.map((t) => (
                  <th key={t.id} scope="col" className="py-2 pr-3 font-medium text-text">
                    {t.name}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {[
                ["Price", ...tiers.map((t) => `${inr(t.price)} ${t.per}`)],
                ["Pro for", "7 days", "1 month at a time", "365 days"],
                ["Renews", "No", "Yes, monthly (cancel anytime)", "No"],
                ["Cost per day", ...tiers.map((t) => t.perDay)],
                ["Pay with", "UPI QR, UPI, card, netbanking", "UPI AutoPay or card · or 1 month by UPI QR", "UPI QR, UPI, card, netbanking"],
                ["Best for", ...tiers.map((t) => t.bestFor)],
              ].map(([label, ...cells]) => (
                <tr key={label}>
                  <th scope="row" className="py-2.5 pr-3 font-medium text-text-2">
                    {label}
                  </th>
                  {cells.map((c, i) => (
                    <td key={i} className="py-2.5 pr-3">
                      {c}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mt-3 text-[12.5px] text-text-3">Buying a pass while you’re on Pro adds its days on top. Prices include all taxes.</p>
        </div>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader title="What Pro adds" />
          <ul className="space-y-2 px-5 pb-5 text-[13.5px] text-text-2">
            {PRO_FEATURES.map((f) => (
              <li key={f} className="flex gap-2">
                <Check className="mt-0.5 size-4 shrink-0 text-cobalt-text" /> {f}
              </li>
            ))}
          </ul>
        </Card>
        <Card>
          <CardHeader title="Payments and invoices" description="Payments are taken on Razorpay. JobPilot never sees your card or UPI details." />
          <div className="px-5 pb-5">
            {paid?.length ? (
              <ul className="divide-y divide-border rounded-[var(--radius-card)] border border-border text-[13px]">
                {paid.map((r) => (
                  <li key={r.id} className="flex items-center justify-between gap-3 px-4 py-2.5">
                    <span>
                      {PLAN_NAME[r.plan] ?? r.plan} · {inr(r.amount_inr)} · {r.paid_at ? fmtDate(r.paid_at) : ""}
                    </span>
                    <a href={`/api/payments/${r.id}/invoice`} target="_blank" rel="noreferrer" className="text-accent hover:underline">
                      Invoice {r.invoice_number}
                    </a>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-[13px] text-subtle">No payments yet.</p>
            )}
            {cfg.outcome_available && (
              <div className="mt-3 flex items-center justify-between gap-4 rounded-[var(--radius-card)] border border-border px-4 py-3">
                <div className="text-[13px]">
                  <b>Outcome plan (experiment):</b> pay {inr(p.outcome)} only after your first interview. We ask, never charge automatically.
                </div>
                <Switch
                  checked={cfg.outcome_plan}
                  onChange={(v) => api.put("/payments/outcome-plan", { enabled: v }).then(() => qc.invalidateQueries({ queryKey: ["pay-config"] }))}
                  label="Outcome plan"
                />
              </div>
            )}
          </div>
        </Card>
      </div>
    </div>
  );
}

/** On the dashboard, for Free accounts: Get Pro and the Week Pass, both leading to the plans page. */
export function UpgradeBanner() {
  const { data: me } = useMe();
  const { data: cfg } = usePayConfig();
  if (!me || me.is_demo || me.plan !== "free" || !cfg) return null;
  const p = cfg.prices;
  return (
    <div className="mb-5 flex flex-wrap items-center justify-between gap-3 rounded-[var(--radius-card)] border border-[color-mix(in_oklab,var(--cobalt)_35%,transparent)] bg-cobalt-subtle px-4 py-3">
      <div className="text-[13.5px]">
        <b>You’re on Free.</b> Get Pro for mock interviews, Proof Link analytics and up to 50 sends a day: {inr(p.week_pass)} for a week, {inr(p.pro_monthly)} a month or{" "}
        {inr(p.year_pass)} a year.
      </div>
      <div className="flex gap-2">
        <Link href="/billing?plan=week_pass" className={buttonClass({ size: "sm" })}>
          <Zap /> Week Pass {inr(p.week_pass)}
        </Link>
        <Link href="/billing?plan=pro" className={buttonClass({ size: "sm", variant: "primary" })}>
          <Sparkles /> Get Pro
        </Link>
      </div>
    </div>
  );
}

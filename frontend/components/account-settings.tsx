"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Copy, CreditCard, Download, Globe, KeyRound, Mail, MessageCircle, Puzzle, ShieldCheck, Trash2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { Field, Input, Switch } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/misc";
import { ApiError, api, signOut } from "@/lib/api";
import {
  useConnectMail,
  useConfirmAge,
  useConsents,
  useCreateRight,
  useCreateToken,
  useDisconnectMail,
  useExtensionTokens,
  useMailAccount,
  useMe,
  useProInterest,
  useQuota,
  useRevokeToken,
  useRights,
  useSaveWhatsApp,
  useSetConsent,
  useSetQuota,
  useStopWhatsApp,
  useTestWhatsApp,
  useUsage,
  useWhatsApp,
} from "@/lib/queries";
import { LANGS, useLang, useT, type Lang } from "@/lib/i18n";
import { ago, cn } from "@/lib/utils";

function DemoNote() {
  return <p className="rounded-lg border border-border bg-surface-2/60 px-3 py-2 text-[12.5px] text-subtle">Not available in the demo. Create a free account to use it.</p>;
}

export function MailCard() {
  const { data: me } = useMe();
  const { data: acct, isLoading } = useMailAccount();
  const connect = useConnectMail();
  const disconnect = useDisconnectMail();
  const [editing, setEditing] = useState(false);
  const [advanced, setAdvanced] = useState(false);
  const [appPassword, setAppPassword] = useState(false);
  const [googling, setGoogling] = useState(false);

  // Back from Google's consent screen: say how it went, once.
  useEffect(() => {
    const result = new URLSearchParams(window.location.search).get("mail");
    if (!result) return;
    const msg: Record<string, () => void> = {
      connected: () => toast.success("Gmail connected", { description: "Approved applications are sent from your Gmail. JobPilot can send only; it can’t read your mail." }),
      cancelled: () => toast("Gmail wasn’t connected"),
      expired: () => toast.error("That sign-in link expired. Try again."),
      failed: () => toast.error("Google didn’t complete the connection. Make sure the “Send email” box is ticked, then try again."),
    };
    msg[result]?.();
    window.history.replaceState(null, "", window.location.pathname + window.location.hash);
  }, []);

  const connectGoogle = async () => {
    setGoogling(true);
    try {
      const { url } = await api.get<{ url: string }>("/mail/google/start");
      window.location.assign(url);
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "Couldn’t start Google sign-in");
      setGoogling(false);
    }
  };
  const google = Boolean(acct?.google_available);

  const submit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const fd = new FormData(e.currentTarget);
    connect.mutate(
      {
        host: String(fd.get("host") || "smtp.gmail.com"),
        port: Number(fd.get("port") || 587),
        username: String(fd.get("username")),
        password: String(fd.get("password")),
        from_name: String(fd.get("from_name") || ""),
      },
      { onSuccess: () => setEditing(false) },
    );
  };

  return (
    <Card id="mail">
      <CardHeader
        icon={<Mail className="size-4" />}
        title="Your email"
        description="Applications you approve are sent from your own address, with the tailored resume attached, so replies come straight to you"
      />
      <div className="space-y-4 p-5">
        {isLoading ? (
          <Skeleton className="h-16" />
        ) : me?.is_demo ? (
          <DemoNote />
        ) : acct?.connected && !editing ? (
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-[var(--radius-card)] border border-success/25 bg-success/5 px-4 py-3">
            <div>
              <div className="flex items-center gap-2 text-[13.5px] font-medium">
                <span className="size-2 rounded-full bg-success" /> Sending as {acct.from_name ? `${acct.from_name} <${acct.from_email}>` : acct.from_email}
              </div>
              <div className="text-[12px] text-subtle">
                {acct.provider === "gmail_oauth" ? "Gmail, connected with Google (send-only access)" : `${acct.host}:${acct.port} · app password`}
                {acct.verified_at && ` · ${ago(acct.verified_at)}`}
              </div>
              {acct.provider !== "gmail_oauth" && google && (
                <button type="button" onClick={connectGoogle} className="mt-1 text-[12px] text-accent hover:underline">
                  Switch to Google sign-in and delete the stored password
                </button>
              )}
            </div>
            <div className="flex gap-2">
              <Button size="sm" onClick={() => setEditing(true)}>Change</Button>
              <Button size="sm" variant="danger" onClick={() => disconnect.mutate()} loading={disconnect.isPending}>Disconnect</Button>
            </div>
          </div>
        ) : google && !appPassword ? (
          <div className="space-y-3">
            <Button variant="primary" onClick={connectGoogle} loading={googling}>
              <Mail /> Connect Gmail with Google
            </Button>
            <p className="text-[12.5px] leading-relaxed text-muted">
              Google asks you to allow one thing: sending email as you. JobPilot can’t read, delete or search your mail, and it only sends applications you approve, at
              least 90 seconds apart. Disconnect any time here or at myaccount.google.com/permissions.
            </p>
            <div className="flex gap-3">
              <button type="button" className="text-[12.5px] text-accent hover:underline" onClick={() => setAppPassword(true)}>
                Not Gmail? Use another mail server
              </button>
              {editing && (
                <button type="button" className="text-[12.5px] text-muted hover:underline" onClick={() => setEditing(false)}>
                  Cancel
                </button>
              )}
            </div>
          </div>
        ) : (
          <form onSubmit={submit} className="space-y-3">
            <div className="rounded-[var(--radius-card)] border border-border bg-surface-2/50 px-4 py-3 text-[12.5px] leading-relaxed text-muted">
              <b className="text-fg">Gmail:</b> turn on 2-Step Verification, then create an app password at{" "}
              <a href="https://myaccount.google.com/apppasswords" target="_blank" rel="noreferrer" className="text-accent hover:underline">
                myaccount.google.com/apppasswords
              </a>{" "}
              and paste the 16 characters below. We check it with Gmail (nothing is sent), then store it encrypted.
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Email address">
                <Input name="username" type="email" required autoComplete="email" defaultValue={acct?.from_email ?? ""} placeholder="you@gmail.com" />
              </Field>
              <Field label="App password">
                <Input name="password" type="password" required autoComplete="off" placeholder="xxxx xxxx xxxx xxxx" />
              </Field>
            </div>
            <Field label="Name shown to recipients (optional)">
              <Input name="from_name" defaultValue={acct?.from_name ?? me?.name ?? ""} placeholder="Aarav Mehta" />
            </Field>
            <button type="button" className="text-[12.5px] text-accent hover:underline" onClick={() => setAdvanced(!advanced)}>
              {advanced ? "Hide" : "Not Gmail? Set the server"}
            </button>
            <div className={cn("grid gap-3 sm:grid-cols-[1fr_110px]", !advanced && "hidden")}>
              <Field label="SMTP server">
                <Input name="host" defaultValue={acct?.host ?? "smtp.gmail.com"} />
              </Field>
              <Field label="Port">
                <Input name="port" type="number" defaultValue={acct?.port ?? 587} />
              </Field>
            </div>
            <div className="flex gap-2">
              <Button type="submit" variant="primary" loading={connect.isPending}>Check and connect</Button>
              {editing && <Button type="button" variant="ghost" onClick={() => setEditing(false)}>Cancel</Button>}
            </div>
          </form>
        )}
      </div>
    </Card>
  );
}

function Meter({ label, used, limit, format = (n: number) => String(n) }: { label: string; used: number; limit: number; format?: (n: number) => string }) {
  const pct = Math.min(100, Math.round((used / Math.max(limit, 1e-9)) * 100));
  return (
    <div>
      <div className="mb-1 flex justify-between text-[12.5px]">
        <span className="text-muted">{label}</span>
        <span className="font-mono tabular-nums">
          {format(used)} / {format(limit)}
        </span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-surface-3">
        <div className={cn("h-full rounded-full", pct >= 100 ? "bg-your-turn" : "bg-cobalt")} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

export function PlanCard() {
  const { data: me } = useMe();
  const { data: u } = useUsage();
  const ask = useProInterest();
  if (!u) return <Skeleton className="h-48" />;
  return (
    <Card id="plan">
      <CardHeader
        icon={<CreditCard className="size-4" />}
        title={
          <span className="flex items-center gap-2">
            Plan & usage <Badge tone={u.plan === "pro" ? "accent" : "neutral"}>{u.plan === "pro" ? "Pro" : "Free"}</Badge>
          </span>
        }
        description="Limits reset on a rolling 24 hours. Background job alerts never stop."
      />
      <div className="space-y-4 p-5">
        <Meter label="Tailored applications today" used={u.drafts} limit={u.limits.drafts_per_day} />
        <Meter label="This week’s quality budget" used={u.week_applications} limit={u.weekly_cap} />
        <Meter label="On-demand runs" used={u.manual_runs} limit={u.limits.manual_runs_per_day} />
        <Meter label="AI budget" used={u.llm_usd} limit={u.limits.llm_usd_per_day} format={(n) => `$${n.toFixed(2)}`} />
        <p className="text-[12px] text-subtle">
          New jobs wake your agents at most every {u.limits.min_refresh_minutes} minute{u.limits.min_refresh_minutes === 1 ? "" : "s"}. Past the AI budget, agents keep
          working with their built-in offline scoring and templates.
        </p>
        {!me?.is_demo && <Billing plan={u.plan} requestPro={() => ask.mutate()} requesting={ask.isPending} requested={u.pro_requested} />}
      </div>
    </Card>
  );
}

type PayConfig = { enabled: boolean; prices: Record<string, number>; plan: string; plan_expires_at: string | null; subscribed: boolean; outcome_plan: boolean; outcome_available: boolean };
type PaidRow = { id: string; plan: string; amount_inr: number; paid_at: string | null; invoice_number: string | null };
const PLAN_NAME: Record<string, string> = { pro_monthly: "Pro, 1 month", pro_month: "Pro, 1 month (UPI QR)", week_pass: "Week Pass", outcome: "Outcome plan" };

type QrStart = { payment_id: string; amount_inr: number; image: string; expires_in_s: number };

/** Scan-to-pay: a single-use Razorpay UPI QR for a fixed amount, shown right here. Any UPI app works. */
function UpiQr({ prices, onPaid }: { prices: Record<string, number>; onPaid: () => void }) {
  const [qr, setQr] = useState<(QrStart & { plan: string; until: number }) | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [left, setLeft] = useState(0);
  useEffect(() => {
    if (!qr) return;
    const tick = setInterval(() => setLeft(Math.max(0, Math.round((qr.until - Date.now()) / 1000))), 1000);
    const poll = setInterval(async () => {
      try {
        const st = await api.get<{ status: string }>(`/payments/qr/${qr.payment_id}/status`);
        if (st.status === "paid") {
          toast.success(qr.plan === "week_pass" ? "Paid. Week Pass is on: 7 days of Pro." : "Paid. Pro is on for a month.");
          setQr(null);
          onPaid();
        }
      } catch {
        /* keep polling */
      }
    }, 3000);
    return () => {
      clearInterval(tick);
      clearInterval(poll);
    };
  }, [qr, onPaid]);
  const start = async (plan: string) => {
    setBusy(plan);
    try {
      const r = await api.post<QrStart>(`/payments/qr/${plan}`);
      setQr({ ...r, plan, until: Date.now() + r.expires_in_s * 1000 });
      setLeft(r.expires_in_s);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Couldn’t create the QR code");
    } finally {
      setBusy(null);
    }
  };
  if (qr) {
    const expired = left === 0;
    return (
      <div className="flex flex-col items-center gap-3 rounded-[var(--radius-card)] border border-border p-4 text-center">
        <div className="text-[14px] font-semibold">
          Scan to pay ₹{qr.amount_inr} · {qr.plan === "week_pass" ? "Week Pass" : "Pro, 1 month"}
        </div>
        {expired ? (
          <p className="text-[13px] text-muted">This QR code expired. Make a new one.</p>
        ) : (
          // Served from our own API (same origin), so the page loads no third-party images.
          // eslint-disable-next-line @next/next/no-img-element
          <img src={qr.image} alt={`UPI QR code to pay ₹${qr.amount_inr}`} width={240} height={240} className="rounded-[var(--radius-control)] bg-white p-2" />
        )}
        <p className="text-[12.5px] text-muted">
          Open GPay, PhonePe, Paytm or any UPI app and scan. {expired ? "" : `Waiting for payment… ${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")} left.`}
        </p>
        <div className="flex gap-2">
          {expired && (
            <Button size="sm" variant="primary" onClick={() => start(qr.plan)}>
              New QR code
            </Button>
          )}
          <Button size="sm" variant="ghost" onClick={() => setQr(null)}>
            Close
          </Button>
        </div>
      </div>
    );
  }
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-[var(--radius-card)] border border-border px-4 py-3">
      <div className="text-[13px]">
        <b>Pay by UPI QR</b> · scan with any UPI app. One-time payment, nothing renews.
      </div>
      <div className="flex gap-2">
        <Button size="sm" loading={busy === "week_pass"} onClick={() => start("week_pass")}>
          Week Pass ₹{prices.week_pass}
        </Button>
        <Button size="sm" loading={busy === "pro_month"} onClick={() => start("pro_month")}>
          Pro 1 month ₹{prices.pro_monthly}
        </Button>
      </div>
    </div>
  );
}

/** Pro by UPI / card on Razorpay's own pages, a Week Pass, cancel in two clicks, and invoices. */
function Billing({ plan, requestPro, requesting, requested }: { plan: string; requestPro: () => void; requesting: boolean; requested: boolean }) {
  const qc = useQueryClient();
  const { data: cfg } = useQuery({ queryKey: ["pay-config"], queryFn: () => api.get<PayConfig>("/payments/config") });
  const { data: paid } = useQuery({ queryKey: ["payments"], queryFn: () => api.get<PaidRow[]>("/payments") });
  const [busy, setBusy] = useState<string | null>(null);
  const [confirm, setConfirm] = useState(false);
  useEffect(() => {
    const p = new URLSearchParams(window.location.search).get("paid");
    if (p) toast.success("Payment received. Your plan updates within a minute of Razorpay confirming it.");
  }, []);
  if (!cfg) return null;
  const go = async (which: string) => {
    setBusy(which);
    try {
      const { url } = await api.post<{ url: string }>(`/payments/checkout/${which}`);
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
  const until = cfg.plan_expires_at ? new Date(cfg.plan_expires_at).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" }) : null;
  return (
    <div className="space-y-3">
      {plan === "pro" && until && (
        <p className="text-[13px]">
          Pro until <b>{until}</b>
          {cfg.subscribed ? ", renews monthly." : ", then Free. Nothing renews."}
        </p>
      )}
      {cfg.enabled ? (
        <>
          <UpiQr prices={cfg.prices} onPaid={() => qc.invalidateQueries()} />
          {!cfg.subscribed && (
            <div className="flex flex-wrap items-center justify-between gap-3 rounded-[var(--radius-card)] border border-accent/25 bg-accent-soft px-4 py-3">
              <div className="text-[13px]">
                <b>Pro ₹{cfg.prices.pro_monthly}/month</b> by UPI or card · or a <b>Week Pass ₹{cfg.prices.week_pass}</b> for 7 days, no renewal
              </div>
              <div className="flex gap-2">
                <Button size="sm" variant="primary" loading={busy === "pro_monthly"} onClick={() => go("pro_monthly")}>
                  Get Pro
                </Button>
                <Button size="sm" loading={busy === "week_pass"} onClick={() => go("week_pass")}>
                  Week Pass
                </Button>
              </div>
            </div>
          )}
          {cfg.subscribed &&
            (confirm ? (
              <div className="flex flex-wrap items-center gap-2 text-[13px]">
                Cancel Pro? You keep it until {until ?? "the end of this period"}.
                <Button size="sm" variant="danger" loading={busy === "cancel"} onClick={cancel}>
                  Yes, cancel
                </Button>
                <Button size="sm" variant="ghost" onClick={() => setConfirm(false)}>
                  Keep Pro
                </Button>
              </div>
            ) : (
              <Button size="sm" variant="ghost" onClick={() => setConfirm(true)}>
                Cancel Pro
              </Button>
            ))}
          {cfg.outcome_available && (
            <div className="flex items-center justify-between gap-4 rounded-[var(--radius-card)] border border-border px-4 py-3">
              <div className="text-[13px]">
                <b>Outcome plan (experiment):</b> pay ₹{cfg.prices.outcome} only after your first interview. We ask, never charge automatically.
              </div>
              <Switch
                checked={cfg.outcome_plan}
                onChange={(v) => api.put("/payments/outcome-plan", { enabled: v }).then(() => qc.invalidateQueries({ queryKey: ["pay-config"] }))}
                label="Outcome plan"
              />
            </div>
          )}
        </>
      ) : (
        plan === "free" && (
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-[var(--radius-card)] border border-accent/25 bg-accent-soft px-4 py-3">
            <div className="text-[13px]">
              <b>Pro</b> · deeper prep, a bigger AI budget and more. Free on request during the beta.
            </div>
            <Button size="sm" variant="primary" onClick={requestPro} loading={requesting} disabled={requested}>
              {requested ? "Requested" : "Request Pro"}
            </Button>
          </div>
        )
      )}
      {!!paid?.length && (
        <ul className="divide-y divide-border rounded-[var(--radius-card)] border border-border text-[13px]">
          {paid.map((p) => (
            <li key={p.id} className="flex items-center justify-between gap-3 px-4 py-2.5">
              <span>
                {PLAN_NAME[p.plan] ?? p.plan} · ₹{p.amount_inr} · {p.paid_at ? new Date(p.paid_at).toLocaleDateString("en-IN") : ""}
              </span>
              <a href={`/api/payments/${p.id}/invoice`} target="_blank" rel="noreferrer" className="text-accent hover:underline">
                Invoice {p.invoice_number}
              </a>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function SecurityCard() {
  const { data: me } = useMe();
  const [loading, setLoading] = useState(false);

  const change = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const form = e.currentTarget;
    const fd = new FormData(form);
    setLoading(true);
    try {
      await api.post("/auth/change-password", { current_password: fd.get("current"), new_password: fd.get("next") });
      toast.success("Password changed", { description: "You’ve been signed out on your other devices." });
      form.reset();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Couldn’t change password");
    } finally {
      setLoading(false);
    }
  };
  const everywhere = () => signOut("/auth/logout-all");

  return (
    <Card>
      <CardHeader icon={<KeyRound className="size-4" />} title="Sign-in & security" />
      <div className="space-y-4 p-5">
        {me?.is_demo ? (
          <DemoNote />
        ) : (
          <>
            <form onSubmit={change} className="grid gap-3 sm:grid-cols-[1fr_1fr_auto] sm:items-end">
              <Field label="Current password">
                <Input name="current" type="password" required autoComplete="current-password" />
              </Field>
              <Field label="New password">
                <Input name="next" type="password" required minLength={8} autoComplete="new-password" />
              </Field>
              <Button type="submit" loading={loading}>Change</Button>
            </form>
            <div className="flex items-center justify-between rounded-[var(--radius-card)] border border-border px-4 py-3">
              <div>
                <div className="text-[13.5px] font-medium">Sign out everywhere</div>
                <div className="text-[12px] text-subtle">Ends every session, on every device, including this one</div>
              </div>
              <Button size="sm" onClick={everywhere}>
                <ShieldCheck className="size-3.5" /> Sign out all
              </Button>
            </div>
          </>
        )}
      </div>
    </Card>
  );
}

export function DataCard() {
  const { data: me } = useMe();
  const router = useRouter();
  const qc = useQueryClient();
  const [confirming, setConfirming] = useState(false);
  const [loading, setLoading] = useState(false);

  const remove = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setLoading(true);
    try {
      await api.del("/account", { password: new FormData(e.currentTarget).get("password") ?? "" });
      qc.clear();
      toast.success("Your account and all its data were deleted");
      router.replace("/");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Couldn’t delete the account");
      setLoading(false);
    }
  };

  return (
    <Card>
      <CardHeader icon={<Download className="size-4" />} title="Your data" description="Download everything JobPilot holds about you, or delete it all" />
      <div className="flex flex-wrap gap-2 p-5">
        <a href="/api/account/export" download className="inline-flex h-9 items-center gap-2 rounded-[10px] border border-border bg-surface-2 px-4 text-sm font-medium hover:border-border-strong">
          <Download className="size-4" /> Export my data
        </a>
        {!confirming ? (
          <Button variant="danger" onClick={() => setConfirming(true)}>
            <Trash2 className="size-4" /> Delete account
          </Button>
        ) : (
          <form onSubmit={remove} className="mt-2 w-full space-y-3 rounded-[var(--radius-card)] border border-danger/25 bg-danger/5 p-4">
            <p className="text-[13px]">This permanently deletes your resume, matches, drafts, tracker and mail connection. It can’t be undone.</p>
            {!me?.is_demo && (
              <Field label="Your password">
                <Input name="password" type="password" required autoComplete="current-password" />
              </Field>
            )}
            <div className="flex gap-2">
              <Button type="submit" variant="danger" loading={loading}>Delete everything</Button>
              <Button type="button" variant="ghost" onClick={() => setConfirming(false)}>Cancel</Button>
            </div>
          </form>
        )}
      </div>
    </Card>
  );
}

const METHOD: Record<string, string> = {
  checkbox: "ticked a box",
  google_oauth: "connected Gmail",
  app_password: "connected your mailbox",
  whatsapp: "on WhatsApp",
  migrated: "carried over when this notice was itemized",
};

export function ConsentCard() {
  const { data } = useConsents();
  const set = useSetConsent();
  const { data: me } = useMe();
  if (!data) return <Skeleton className="h-40" />;
  return (
    <Card id="privacy">
      <CardHeader
        icon={<ShieldCheck className="size-4" />}
        title="Privacy & consent"
        description={`One switch per purpose (notice version ${data.version}). Turning one off is as easy as turning it on, and stops that use at once.`}
      />
      <div className="space-y-2 p-5">
        {data.purposes.map((p) => (
          <div key={p.purpose} className="rounded-[var(--radius-card)] border border-border px-4 py-3">
            <div className="flex items-center justify-between gap-4">
              <div>
                <div className="text-[13.5px] font-medium">{p.description}</div>
                <div className="text-[12px] text-subtle">
                  {p.required
                    ? "Needed for your account; ends when you delete it"
                    : p.granted && p.granted_at
                      ? `Agreed ${ago(p.granted_at)}${p.method ? ` (${METHOD[p.method] ?? p.method})` : ""}${p.notice_version ? ` · notice ${p.notice_version}` : ""}`
                      : "Off"}
                </div>
              </div>
              <Switch checked={p.granted} onChange={(v) => !p.required && !me?.is_demo && set.mutate({ purpose: p.purpose, granted: v })} label={p.purpose} />
            </div>
            {p.notice && (
              <details className="mt-2 text-[12.5px] text-muted [&_summary::-webkit-details-marker]:hidden">
                <summary className="cursor-pointer list-none text-accent hover:underline">What this uses and why</summary>
                <dl className="mt-2 grid gap-1.5 sm:grid-cols-[90px_1fr]">
                  <dt className="text-subtle">Data</dt>
                  <dd>{p.notice.data}</dd>
                  <dt className="text-subtle">Why</dt>
                  <dd>{p.notice.why}</dd>
                  <dt className="text-subtle">Kept</dt>
                  <dd>{p.notice.retention}</dd>
                  <dt className="text-subtle">To stop</dt>
                  <dd>{p.notice.withdraw}</dd>
                </dl>
              </details>
            )}
          </div>
        ))}
      </div>
    </Card>
  );
}

const RIGHT_KINDS: [string, string][] = [
  ["grievance", "A complaint or question about my data"],
  ["access", "A copy of my data, explained"],
  ["correction", "Correct something I can’t edit myself"],
  ["erasure", "Erase specific data"],
  ["nomination", "Nominate someone to act for me"],
];

export function RightsCard() {
  const { data } = useRights();
  const { data: me } = useMe();
  const create = useCreateRight();
  const [kind, setKind] = useState("grievance");
  if (!data) return <Skeleton className="h-40" />;
  const submit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const form = e.currentTarget;
    create.mutate({ kind, details: String(new FormData(form).get("details") || "") }, { onSuccess: () => form.reset() });
  };
  return (
    <Card id="rights">
      <CardHeader
        icon={<ShieldCheck className="size-4" />}
        title="Your data rights"
        description={`Export, correction, erasure and consent withdrawal work instantly above. For anything else, write to us: we reply within ${data.sla_days} days.`}
      />
      <div className="space-y-4 p-5">
        {me?.is_demo ? (
          <DemoNote />
        ) : (
          <form onSubmit={submit} className="space-y-3">
            <Field label="What do you need?">
              <select
                value={kind}
                onChange={(e) => setKind(e.target.value)}
                className="h-10 w-full rounded-[var(--radius-control)] border border-border bg-surface px-3 text-[14px]"
              >
                {RIGHT_KINDS.map(([k, l]) => (
                  <option key={k} value={k}>
                    {l}
                  </option>
                ))}
              </select>
            </Field>
            {data.self_service[kind] && <p className="text-[12.5px] text-muted">Quicker: {data.self_service[kind]}</p>}
            <Field label="Details">
              <textarea
                name="details"
                rows={3}
                maxLength={4000}
                required
                className="w-full rounded-[var(--radius-control)] border border-border bg-surface px-3 py-2 text-[14px]"
              />
            </Field>
            <Button type="submit" loading={create.isPending}>
              Send request
            </Button>
          </form>
        )}
        {data.requests.length > 0 && (
          <ul className="divide-y divide-border rounded-[var(--radius-card)] border border-border">
            {data.requests.map((r) => (
              <li key={r.id} className="px-4 py-3 text-[13px]">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="font-medium capitalize">{r.kind}</span>
                  <Badge tone={r.status === "resolved" ? "success" : "outline"}>
                    {r.status === "resolved" ? "Answered" : `Reply due ${new Date(r.due_at).toLocaleDateString("en-IN", { day: "numeric", month: "short" })}`}
                  </Badge>
                </div>
                {r.response && <p className="mt-1.5 text-muted">{r.response}</p>}
              </li>
            ))}
          </ul>
        )}
      </div>
    </Card>
  );
}

/** English / हिन्दी / मराठी: saved on the account (also used for WhatsApp messages). */
export function LanguageCard() {
  const [lang, setLocal] = useLang();
  const qc = useQueryClient();
  const t = useT();
  const choose = async (l: Lang) => {
    setLocal(l);
    await api.put("/account/language", { language: l });
    qc.invalidateQueries({ queryKey: ["me"] });
  };
  return (
    <Card id="language">
      <CardHeader icon={<Globe className="size-4" />} title={t("settings.language")} description={t("settings.language.sub")} />
      <div role="radiogroup" aria-label={t("settings.language")} className="flex flex-wrap gap-2 p-5">
        {LANGS.map((l) => (
          <button
            key={l.v}
            type="button"
            role="radio"
            aria-checked={lang === l.v}
            onClick={() => choose(l.v)}
            className={cn("min-h-11 rounded-[var(--radius-control)] border px-4 text-[14px]", lang === l.v ? "border-cobalt bg-cobalt-subtle font-medium" : "border-border text-muted")}
          >
            {l.label}
          </button>
        ))}
      </div>
    </Card>
  );
}

/** The quality quota: approved sends per day, default 5, up to the plan's maximum. */
export function QuotaCard() {
  const { data: q } = useQuota();
  const set = useSetQuota();
  const [cap, setCap] = useState<number | null>(null);
  if (!q) return <Skeleton className="h-32" />;
  const value = cap ?? q.cap;
  return (
    <Card id="quota">
      <CardHeader
        icon={<ShieldCheck className="size-4" />}
        title="Daily send quota"
        description="Fewer, stronger applications get more interviews. The crew never sends more than this in a day, and resets at midnight IST."
      />
      <div className="space-y-3 p-5">
        <div className="flex items-center justify-between text-[13.5px]">
          <span>Approved sends a day</span>
          <span className="num font-semibold">{value}</span>
        </div>
        <input
          type="range"
          min={1}
          max={q.max}
          value={value}
          onChange={(e) => setCap(Number(e.target.value))}
          aria-label="Approved sends a day"
          className="w-full accent-[var(--cobalt)]"
        />
        <div className="flex items-center justify-between text-[12px] text-subtle">
          <span>
            {q.used} used today · up to {q.max} on your plan
          </span>
          <Button size="sm" disabled={value === q.cap} loading={set.isPending} onClick={() => set.mutate({ cap: value }, { onSuccess: () => setCap(null) })}>
            Save
          </Button>
        </div>
      </div>
    </Card>
  );
}

/** Accounts created before the age gate confirm once; until then the agents don't run (DPDP Act s.9). */
export function AgeGateBanner() {
  const { data: me } = useMe();
  const confirm = useConfirmAge();
  const [minor, setMinor] = useState(false);
  if (!me || me.is_demo || me.adult_confirmed_at) return null;
  return (
    <div role="region" aria-label="Confirm your age" className="mb-5 rounded-[var(--radius-card)] border border-[color-mix(in_oklab,var(--your-turn-fill)_40%,transparent)] bg-[color-mix(in_oklab,var(--your-turn-fill)_10%,transparent)] p-4">
      {minor ? (
        <p className="text-[13.5px] leading-relaxed">
          Thanks for telling us. JobPilot can’t process data for students under 18 yet, because the law needs a parent’s verifiable consent that we can’t collect. Your agents are
          paused. You can export or delete your account in Settings → Your data.
        </p>
      ) : (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-[13.5px] leading-relaxed">
            <b>One quick check:</b> are you 18 or older? Your agents are paused until you answer.
          </p>
          <div className="flex gap-2">
            <Button size="sm" variant="primary" loading={confirm.isPending} onClick={() => confirm.mutate({ adult: true })}>
              I’m 18 or older
            </Button>
            <Button size="sm" variant="ghost" onClick={() => confirm.mutate({ adult: false }, { onSettled: () => setMinor(true) })}>
              I’m under 18
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

export function WhatsAppCard() {
  const { data: me } = useMe();
  const { data: w } = useWhatsApp();
  const save = useSaveWhatsApp();
  const stop = useStopWhatsApp();
  const test = useTestWhatsApp();
  const [agree, setAgree] = useState(false);
  if (!w) return <Skeleton className="h-40" />;
  const submit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const fd = new FormData(e.currentTarget);
    save.mutate({ number: String(fd.get("number")), hour: Number(fd.get("hour")), consent: agree });
  };
  return (
    <Card id="whatsapp">
      <CardHeader icon={<MessageCircle className="size-4" />} title="WhatsApp daily digest" description="Your 3–5 best new fits each morning, with a link to review the drafts. Reply STOP any time." />
      <div className="space-y-3 p-5">
        {!w.available && <p className="rounded-[var(--radius-card)] border border-border bg-surface-2/60 px-3 py-2 text-[12.5px] text-subtle">Not switched on for this server yet. Save your number now and the digest starts when it is.</p>}
        {me?.is_demo ? (
          <DemoNote />
        ) : w.enabled ? (
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-[var(--radius-card)] border border-success/25 bg-success/5 px-4 py-3">
            <div className="text-[13.5px]">
              <b>+{w.number}</b> · every day at {w.hour}:00 IST{w.last_sent_at && <span className="text-subtle"> · last sent {ago(w.last_sent_at)}</span>}
            </div>
            <div className="flex gap-2">
              {w.available && <Button size="sm" onClick={() => test.mutate(undefined)} loading={test.isPending}>Send a test</Button>}
              <Button size="sm" variant="danger" onClick={() => stop.mutate(undefined)}>Turn off</Button>
            </div>
          </div>
        ) : (
          <form onSubmit={submit} className="space-y-3">
            <div className="grid gap-3 sm:grid-cols-[1fr_140px]">
              <Field label="WhatsApp number"><Input name="number" required placeholder="+91 98765 43210" defaultValue={w.number ? `+${w.number}` : ""} /></Field>
              <Field label="Time (IST)">
                <select name="hour" defaultValue={w.hour} className="h-10 w-full rounded-[var(--radius-card)] border border-border bg-surface-solid/60 px-3 text-sm">
                  {Array.from({ length: 24 }, (_, h) => <option key={h} value={h}>{`${h}:00`}</option>)}
                </select>
              </Field>
            </div>
            <label className="flex items-start gap-2 text-[12.5px] text-muted">
              <input type="checkbox" checked={agree} onChange={(e) => setAgree(e.target.checked)} className="mt-0.5 accent-[var(--accent)]" />
              I agree to receive one WhatsApp message a day from JobPilot at this number.
            </label>
            <Button type="submit" variant="primary" loading={save.isPending} disabled={!agree}>Turn on the digest</Button>
          </form>
        )}
      </div>
    </Card>
  );
}

export function ExtensionCard() {
  const { data: me } = useMe();
  const { data: tokens } = useExtensionTokens();
  const create = useCreateToken();
  const revoke = useRevokeToken();
  const [fresh, setFresh] = useState<string | null>(null);
  return (
    <Card id="extension">
      <CardHeader icon={<Puzzle className="size-4" />} title="Chrome autofill extension" description="Fills Greenhouse, Lever and Ashby forms with your details and tailored resume. You click Submit." />
      <div className="space-y-3 p-5">
        {me?.is_demo ? (
          <DemoNote />
        ) : (
          <>
            {fresh && (
              <div className="rounded-[var(--radius-card)] border border-border-strong bg-accent-soft p-4 text-[13px]">
                <b>Your token</b>, shown only once. Paste it into the extension’s settings.
                <div className="mt-2 flex gap-2">
                  <Input readOnly value={fresh} className="font-mono text-[12px]" />
                  <Button size="icon" aria-label="Copy token" onClick={() => (navigator.clipboard.writeText(fresh), toast.success("Copied"))}>
                    <Copy className="size-4" />
                  </Button>
                </div>
              </div>
            )}
            {tokens?.map((t) => (
              <div key={t.id} className="flex items-center justify-between rounded-[var(--radius-card)] border border-border px-4 py-2.5">
                <div className="text-[13px]">
                  <b>{t.name}</b> <span className="font-mono text-subtle">{t.prefix}…</span>
                  <div className="text-[12px] text-subtle">{t.last_used_at ? `Used ${ago(t.last_used_at)}` : `Created ${ago(t.created_at)}, not used yet`}</div>
                </div>
                <Button size="sm" variant="ghost" onClick={() => revoke.mutate(t.id)}>Revoke</Button>
              </div>
            ))}
            <div className="flex flex-wrap gap-2">
              <Button variant="primary" onClick={() => create.mutate("Chrome extension", { onSuccess: (r) => setFresh(r.token) })} loading={create.isPending}>
                Create token
              </Button>
              <Button onClick={() => toast.message("Install the extension", { description: "chrome://extensions → Developer mode → Load unpacked → pick the extension/ folder, then paste this token in its settings." })}>
                How to install
              </Button>
            </div>
          </>
        )}
      </div>
    </Card>
  );
}

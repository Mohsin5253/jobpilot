"use client";

import { useQueryClient } from "@tanstack/react-query";
import { Copy, CreditCard, Download, KeyRound, Mail, MessageCircle, Puzzle, ShieldCheck, Trash2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { Field, Input, Switch } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/misc";
import { ApiError, api, signOut } from "@/lib/api";
import {
  useConnectMail,
  useConsents,
  useCreateToken,
  useDisconnectMail,
  useExtensionTokens,
  useMailAccount,
  useMe,
  useProInterest,
  useRevokeToken,
  useSaveWhatsApp,
  useSetConsent,
  useStopWhatsApp,
  useTestWhatsApp,
  useUsage,
  useWhatsApp,
} from "@/lib/queries";
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
                {acct.host}:{acct.port}
                {acct.verified_at && ` · verified ${ago(acct.verified_at)}`}
              </div>
            </div>
            <div className="flex gap-2">
              <Button size="sm" onClick={() => setEditing(true)}>Change</Button>
              <Button size="sm" variant="danger" onClick={() => disconnect.mutate()} loading={disconnect.isPending}>Disconnect</Button>
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
        {u.plan === "free" && !me?.is_demo && (
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-[var(--radius-card)] border border-accent/25 bg-accent-soft px-4 py-3">
            <div className="text-[13px]">
              <b>Pro</b> · 50 applications a day, instant alerts, 10× AI budget. Free during the beta.
            </div>
            <Button size="sm" variant="primary" onClick={() => ask.mutate()} loading={ask.isPending} disabled={u.pro_requested}>
              {u.pro_requested ? "Requested" : "Request Pro"}
            </Button>
          </div>
        )}
      </div>
    </Card>
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

export function ConsentCard() {
  const { data } = useConsents();
  const set = useSetConsent();
  const { data: me } = useMe();
  if (!data) return <Skeleton className="h-40" />;
  return (
    <Card id="privacy">
      <CardHeader icon={<ShieldCheck className="size-4" />} title="Privacy & consent" description={`What you’ve agreed to (notice version ${data.version}). Turning one off stops that feature at once.`} />
      <div className="space-y-2 p-5">
        {data.purposes.map((p) => (
          <div key={p.purpose} className="flex items-center justify-between gap-4 rounded-[var(--radius-card)] border border-border px-4 py-3">
            <div>
              <div className="text-[13.5px] font-medium">{p.description}</div>
              <div className="text-[12px] text-subtle">
                {p.required ? "Needed for your account; ends when you delete it" : p.granted && p.granted_at ? `Agreed ${ago(p.granted_at)}` : "Off"}
              </div>
            </div>
            <Switch checked={p.granted} onChange={(v) => !p.required && !me?.is_demo && set.mutate({ purpose: p.purpose, granted: v })} label={p.purpose} />
          </div>
        ))}
      </div>
    </Card>
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

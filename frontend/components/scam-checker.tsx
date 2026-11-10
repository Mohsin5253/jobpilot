"use client";

import { AlertTriangle, Check, CircleHelp, Loader2, Share2, ShieldAlert, ShieldCheck, Upload, X } from "lucide-react";
import { useRef, useState, type FormEvent } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";

type CheckRow = { id: string; label: string; status: "pass" | "warn" | "fail" | "unverified"; evidence: string[] };
type Result = { verdict: "Likely safe" | "Suspicious" | "Likely scam"; score: number; checks: CheckRow[]; advice: string[]; verification_id: string };

const TONE = {
  "Likely scam": { icon: ShieldAlert, color: "var(--error)", badge: "danger" as const },
  Suspicious: { icon: AlertTriangle, color: "var(--your-turn)", badge: "warning" as const },
  "Likely safe": { icon: ShieldCheck, color: "var(--done)", badge: "success" as const },
};
const ICON = { fail: X, warn: AlertTriangle, pass: Check, unverified: CircleHelp };
const ORDER = { fail: 0, warn: 1, unverified: 2, pass: 3 };

export function ScamChecker() {
  const [text, setText] = useState("");
  const [url, setUrl] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<Result | null>(null);
  const [reported, setReported] = useState<string | null>(null);
  const [agree, setAgree] = useState(false);
  const out = useRef<HTMLDivElement>(null);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setReported(null);
    try {
      const fd = new FormData();
      fd.set("text", text);
      fd.set("url", url);
      if (file) fd.set("file", file);
      const res = await fetch("/api/scam-check", { method: "POST", body: fd });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new ApiError(res.status, typeof body.detail === "string" ? body.detail : "Couldn’t check that. Try again.");
      setResult(body as Result);
      requestAnimationFrame(() => out.current?.focus());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn’t check that. Try again.");
    } finally {
      setBusy(false);
    }
  };

  const report = async () => {
    if (!result) return;
    const res = await fetch(`/api/scam-check/${result.verification_id}/report`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ text, url, consent: true }),
    });
    const body = await res.json().catch(() => ({}));
    setReported(res.ok ? body.detail : body.detail ?? "Couldn’t save the report");
  };

  const share = async () => {
    if (!result) return;
    const ids = result.checks.filter((c) => c.status === "fail" || c.status === "warn").map((c) => c.id).slice(0, 3).join(",");
    const card = `/scam-card?v=${encodeURIComponent(result.verdict)}&s=${result.score}&r=${ids}`;
    const page = `${location.origin}/scam-check`;
    const msg = `I checked an internship offer with JobPilot Scam Shield: ${result.verdict} (${result.score}/100 risk). Never pay to get an internship. Check yours free: ${page}`;
    try {
      const blob = await (await fetch(card)).blob();
      const files = [new File([blob], "scam-check.png", { type: "image/png" })];
      if (navigator.canShare?.({ files })) {
        await navigator.share({ files, text: msg });
        return;
      }
    } catch {
      /* fall back to a WhatsApp link */
    }
    window.open(`https://wa.me/?text=${encodeURIComponent(msg)}`, "_blank", "noopener");
  };

  const tone = result ? TONE[result.verdict] : null;
  return (
    <div className="mt-8">
      <form onSubmit={submit} className="card space-y-4 p-4 md:p-5">
        <label className="block">
          <span className="text-[13.5px] font-medium">The message or offer</span>
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            rows={7}
            maxLength={20000}
            placeholder="Paste the WhatsApp, Telegram or email message here…"
            className="mt-1.5 w-full rounded-[var(--radius-control)] border border-border bg-surface px-3 py-2.5 text-[15px] leading-relaxed"
          />
        </label>
        <div className="grid gap-3 sm:grid-cols-[1fr_auto] sm:items-end">
          <label className="block">
            <span className="text-[13.5px] font-medium">Link (optional)</span>
            <input
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              inputMode="url"
              placeholder="https://…"
              className="mt-1.5 h-11 w-full rounded-[var(--radius-control)] border border-border bg-surface px-3 text-[15px]"
            />
          </label>
          <label className="inline-flex h-11 cursor-pointer items-center justify-center gap-2 rounded-[var(--radius-control)] border border-border px-4 text-[14px] text-text-2 hover:border-border-strong hover:text-text">
            <Upload className="size-4" /> {file ? file.name.slice(0, 24) : "Offer letter (PDF or image)"}
            <input type="file" accept=".pdf,.png,.jpg,.jpeg,.webp,.txt" className="sr-only" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
          </label>
        </div>
        {error && (
          <p role="alert" className="text-[13.5px] text-[var(--error)]">
            {error}
          </p>
        )}
        <Button type="submit" variant="primary" size="lg" className="w-full sm:w-auto" loading={busy} disabled={!text.trim() && !url.trim() && !file}>
          Check it
        </Button>
        <p className="text-[12.5px] text-text-3">Nothing you paste or upload is saved. We keep only an anonymous count of verdicts.</p>
      </form>

      <div ref={out} tabIndex={-1} aria-live="polite" className="outline-none">
        {busy && (
          <p className="mt-6 flex items-center gap-2 text-[14px] text-text-2">
            <Loader2 className="size-4 animate-spin" /> Checking…
          </p>
        )}
        {result && tone && (
          <section className="mt-8 space-y-5" aria-label="Result">
            <div className="card flex items-center gap-4 p-5" style={{ borderColor: `color-mix(in oklab, ${tone.color} 45%, transparent)` }}>
              <tone.icon className="size-10 shrink-0" style={{ color: tone.color }} />
              <div className="min-w-0 flex-1">
                <h2 className="text-[24px] font-semibold tracking-[-0.02em]" style={{ color: tone.color }}>
                  {result.verdict}
                </h2>
                <p className="num text-[13px] text-text-2">Risk score {result.score}/100</p>
              </div>
              <Button onClick={share} className="shrink-0">
                <Share2 /> Share
              </Button>
            </div>

            <div className="card p-5">
              <h3 className="text-[16px] font-semibold">What to do</h3>
              <ul className="mt-3 space-y-2 text-[14.5px] leading-relaxed text-text-2">
                {result.advice.map((a) => (
                  <li key={a} className="flex gap-2.5">
                    <span aria-hidden className="mt-[9px] size-1.5 shrink-0 rounded-full" style={{ background: tone.color }} />
                    <span>
                      {a.includes("cybercrime.gov.in") ? (
                        <>
                          {a.split("cybercrime.gov.in")[0]}
                          <a href="https://cybercrime.gov.in" target="_blank" rel="noopener noreferrer" className="text-cobalt-text underline">
                            cybercrime.gov.in
                          </a>
                          {a.split("cybercrime.gov.in")[1]}
                        </>
                      ) : (
                        a
                      )}
                    </span>
                  </li>
                ))}
              </ul>
            </div>

            <div className="card divide-y divide-border">
              {[...result.checks].sort((a, b) => ORDER[a.status] - ORDER[b.status]).map((c) => {
                const Icon = ICON[c.status];
                return (
                  <div key={c.id} className="flex gap-3 px-5 py-3.5">
                    <Icon
                      className={cn("mt-0.5 size-4 shrink-0", c.status === "pass" ? "text-done" : c.status === "unverified" ? "text-text-3" : "")}
                      style={c.status === "fail" ? { color: "var(--error)" } : c.status === "warn" ? { color: "var(--your-turn)" } : undefined}
                    />
                    <div className="min-w-0">
                      <div className="text-[14px] font-medium">
                        {c.label} {c.status === "unverified" && <Badge tone="outline">Unverified</Badge>}
                      </div>
                      {c.evidence.length > 0 && c.status !== "pass" && (
                        <ul className="mt-1 space-y-1">
                          {c.evidence.map((e) => (
                            <li key={e} className="rounded-[6px] bg-elevated px-2 py-1 text-[12.5px] break-words text-text-2">
                              “{e}”
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>

            {result.verdict !== "Likely safe" && (
              <div className="card p-5">
                <h3 className="text-[16px] font-semibold">Help warn other students</h3>
                {reported ? (
                  <p className="mt-2 text-[14px] text-text-2">{reported}</p>
                ) : (
                  <>
                    <label className="mt-2 flex items-start gap-2.5 text-[13.5px] text-text-2">
                      <input type="checkbox" checked={agree} onChange={(e) => setAgree(e.target.checked)} className="mt-0.5 size-4 accent-[var(--cobalt)]" />
                      Save a redacted copy of this message (phone numbers, names in email addresses and ID numbers removed) so JobPilot can spot this scam for others.
                    </label>
                    <Button className="mt-3" disabled={!agree} onClick={report}>
                      Report this scam
                    </Button>
                  </>
                )}
              </div>
            )}
          </section>
        )}
      </div>
    </div>
  );
}

"use client";

import { ArrowRight } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";

import { AgentHero } from "@/components/agents/agent-avatar";
import { AuthCanvas } from "@/components/auth-card";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/input";
import { api, ApiError } from "@/lib/api";
import { useStartDemo } from "@/lib/demo";

const GOOGLE_NOTES: Record<string, string> = {
  confirm: "Tick both boxes, then continue with Google.",
  no_account: "No JobPilot account uses that Google email yet. Tick the boxes below and continue with Google to create one.",
  unverified: "Google says that email address isn’t verified, so we can’t use it.",
  expired: "That sign-in took too long or started in another browser. Please try again.",
  failed: "Google didn’t complete the sign-in. Please try again.",
};

function GoogleG() {
  return (
    <svg viewBox="0 0 48 48" aria-hidden className="size-[18px]">
      <path fill="#EA4335" d="M24 9.5c3.5 0 6.6 1.2 9.1 3.6l6.8-6.8C35.8 2.4 30.3 0 24 0 14.6 0 6.6 5.4 2.7 13.3l7.9 6.1C12.5 13.6 17.8 9.5 24 9.5z" />
      <path fill="#4285F4" d="M46.1 24.5c0-1.6-.1-3.1-.4-4.5H24v9h12.4c-.5 2.9-2.2 5.3-4.6 7l7.3 5.7c4.3-4 7-9.9 7-17.2z" />
      <path fill="#FBBC05" d="M10.6 28.6c-.5-1.4-.8-3-.8-4.6s.3-3.2.8-4.6l-7.9-6.1C1 16.6 0 20.2 0 24s1 7.4 2.7 10.7l7.9-6.1z" />
      <path fill="#34A853" d="M24 48c6.5 0 11.9-2.1 15.9-5.8l-7.3-5.7c-2 1.4-4.7 2.3-8.6 2.3-6.2 0-11.5-4.1-13.4-9.9l-7.9 6.1C6.6 42.6 14.6 48 24 48z" />
    </svg>
  );
}

export function AuthForm({ mode }: { mode: "login" | "register" }) {
  const router = useRouter();
  const params = useSearchParams();
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const demo = useStartDemo();
  const [google, setGoogle] = useState(false);
  const [adult, setAdult] = useState(false);
  const [agreed, setAgreed] = useState(false);
  useEffect(() => {
    fetch("/api/auth/providers")
      .then((r) => (r.ok ? r.json() : { google: false }))
      .then((p) => setGoogle(Boolean(p.google)))
      .catch(() => setGoogle(false));
  }, []);
  const googleNote = GOOGLE_NOTES[params.get("google") ?? ""];
  const withGoogle = () => {
    if (mode === "register" && !(adult && agreed)) {
      setError("Tick both boxes above first, then continue with Google.");
      return;
    }
    const q = new URLSearchParams({ mode, ...(mode === "register" ? { adult: "1", consent: "1" } : {}), ...(params.get("next") ? { next: params.get("next")! } : {}) });
    window.location.assign(`/api/auth/google/start?${q}`);
  };

  const submit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const fd = new FormData(e.currentTarget);
    setLoading(true);
    setError(null);
    try {
      const body: Record<string, unknown> = Object.fromEntries(fd);
      if (mode === "register") {
        body.consent = fd.get("consent") === "on";
        body.adult = fd.get("adult") === "on";
      }
      await api.post(`/auth/${mode}`, body);
      router.replace(mode === "register" ? "/onboarding" : params.get("next") || "/dashboard");
      router.refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong");
      setLoading(false);
    }
  };

  return (
    <AuthCanvas>
      <div className="flex w-full max-w-[860px] items-center justify-center gap-10">
        {/* Pilot sits beside the form from 768px, facing it; phones get the form alone. */}
        <div className="hidden w-[260px] shrink-0 flex-col items-center gap-5 text-center md:flex">
          <AgentHero agent="pilot" size={200} />
          <div className="relative rounded-[var(--radius-card)] border border-border-strong bg-elevated px-4 py-3 text-[14px] leading-relaxed">
            <span aria-hidden className="absolute -top-[7px] left-1/2 size-3 -translate-x-1/2 rotate-45 border-t border-l border-border-strong bg-elevated" />
            {mode === "login" ? "Welcome back. The crew kept working while you were away." : "Hi, I’m Pilot. Upload your resume and my crew does the daily grind. You approve every send."}
          </div>
        </div>

        <div className="panel w-full max-w-[400px] p-6 md:p-8">
          <h1 className="font-display text-[clamp(28px,4vw,36px)] leading-tight">{mode === "login" ? "Welcome back" : "Create your account"}</h1>
          <p className="mt-1.5 text-[14px] text-text-2">{mode === "login" ? "Sign in to see what your crew found." : "Free to start. Nothing is sent without your approval."}</p>
        {googleNote && (
          <p role="status" className="mt-4 rounded-[var(--radius-control)] border border-border bg-elevated px-3 py-2 text-[13px] text-text-2">
            {googleNote}
          </p>
        )}
        <form onSubmit={submit} className="mt-7 space-y-4">
          {mode === "register" && (
            <Field label="Name">
              <Input name="name" autoComplete="name" placeholder="Aarav Mehta" />
            </Field>
          )}
          <Field label="Email">
            <Input name="email" type="email" required autoComplete="email" placeholder="you@college.edu" />
          </Field>
          <Field
            label={
              <span className="flex items-center justify-between">
                Password
                {mode === "login" && (
                  <Link href="/forgot-password" className="text-[12.5px] font-normal text-cobalt-text hover:underline">
                    Forgot password?
                  </Link>
                )}
              </span>
            }
            hint={mode === "register" ? "At least 8 characters" : undefined}
          >
            <Input name="password" type="password" required minLength={mode === "register" ? 8 : 1} autoComplete={mode === "login" ? "current-password" : "new-password"} />
          </Field>
          {mode === "register" && (
            <label className="flex items-start gap-2.5 text-[12.5px] leading-relaxed text-text-2">
              <input name="adult" type="checkbox" required checked={adult} onChange={(e) => setAdult(e.target.checked)} className="mt-0.5 size-4 shrink-0 accent-[var(--cobalt)]" />
              <span>I am 18 or older.</span>
            </label>
          )}
          {mode === "register" && (
            <label className="flex items-start gap-2.5 text-[12.5px] leading-relaxed text-text-2">
              <input name="consent" type="checkbox" required checked={agreed} onChange={(e) => setAgreed(e.target.checked)} className="mt-0.5 size-4 shrink-0 accent-[var(--cobalt)]" />
              <span>
                I agree that JobPilot may process my resume and preferences to find and prepare applications for me, as described in the{" "}
                <Link href="/privacy" className="text-cobalt-text underline">Privacy policy</Link> and the{" "}
                <Link href="/trust#consent" className="text-cobalt-text underline">consent notice</Link>. Other uses (sending, a public proof page, WhatsApp) are
                separate switches I can turn on later. I can export or delete my data any time.
              </span>
            </label>
          )}
          {error && <p role="alert" className="rounded-[var(--radius-control)] border border-[color-mix(in_oklab,var(--error)_30%,transparent)] bg-[color-mix(in_oklab,var(--error)_10%,transparent)] px-3 py-2 text-[13px] text-[var(--error)]">{error}</p>}
          <Button type="submit" variant="primary" size="lg" className="w-full" loading={loading}>
            {mode === "login" ? "Sign in" : "Create account"}
            {!loading && <ArrowRight />}
          </Button>
          {google && (
            <Button type="button" size="lg" className="w-full" onClick={withGoogle}>
              <GoogleG /> {mode === "login" ? "Sign in with Google" : "Sign up with Google"}
            </Button>
          )}
        </form>
          <div className="my-5 flex items-center gap-3 text-[12px] text-text-3">
            <span className="h-px flex-1 bg-border" /> or <span className="h-px flex-1 bg-border" />
          </div>
          <Button type="button" size="lg" className="w-full" onClick={demo.start} loading={demo.loading}>
            Try the live demo, no sign-up
          </Button>
          {mode === "register" && (
            <p className="mt-4 text-center text-[12.5px] text-text-3">
              See also the{" "}
              <Link href="/terms" className="underline">
                Terms
              </Link>
              .
            </p>
          )}
          <p className="mt-5 text-center text-[14px] text-text-2">
            {mode === "login" ? "New here? " : "Already have an account? "}
            <Link href={mode === "login" ? "/register" : "/login"} className="inline-flex min-h-11 items-center font-medium text-cobalt-text hover:underline">
              {mode === "login" ? "Create an account" : "Sign in"}
            </Link>
          </p>
        </div>
      </div>
    </AuthCanvas>
  );
}

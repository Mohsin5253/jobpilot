"use client";

import { ArrowRight } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState, type FormEvent } from "react";

import { AgentHero } from "@/components/agents/agent-avatar";
import { AuthCanvas } from "@/components/auth-card";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/input";
import { api, ApiError } from "@/lib/api";
import { useStartDemo } from "@/lib/demo";

export function AuthForm({ mode }: { mode: "login" | "register" }) {
  const router = useRouter();
  const params = useSearchParams();
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const demo = useStartDemo();

  const submit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const fd = new FormData(e.currentTarget);
    setLoading(true);
    setError(null);
    try {
      const body: Record<string, unknown> = Object.fromEntries(fd);
      if (mode === "register") body.consent = fd.get("consent") === "on";
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
              <input name="consent" type="checkbox" required className="mt-0.5 size-4 shrink-0 accent-[var(--cobalt)]" />
              <span>
                I agree that JobPilot may process my resume and preferences to find and prepare applications for me, as described in the{" "}
                <Link href="/privacy" className="text-cobalt-text underline">Privacy policy</Link>. I can export or delete my data any time.
              </span>
            </label>
          )}
          {error && <p role="alert" className="rounded-[var(--radius-control)] border border-[color-mix(in_oklab,var(--error)_30%,transparent)] bg-[color-mix(in_oklab,var(--error)_10%,transparent)] px-3 py-2 text-[13px] text-[var(--error)]">{error}</p>}
          <Button type="submit" variant="primary" size="lg" className="w-full" loading={loading}>
            {mode === "login" ? "Sign in" : "Create account"}
            {!loading && <ArrowRight />}
          </Button>
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

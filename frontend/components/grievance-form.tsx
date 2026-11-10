"use client";

import { useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { ApiError, api } from "@/lib/api";

/** Public grievance form on /trust: no account needed. */
export function GrievanceForm() {
  const [state, setState] = useState<"idle" | "sending" | "sent">("idle");
  const [error, setError] = useState<string | null>(null);
  const [due, setDue] = useState("");
  const submit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const fd = new FormData(e.currentTarget);
    setState("sending");
    setError(null);
    try {
      const r = await api.post<{ due_at: string }>("/public/grievance", { email: fd.get("email"), details: fd.get("details") });
      setDue(new Date(r.due_at).toLocaleDateString("en-IN", { day: "numeric", month: "long", year: "numeric" }));
      setState("sent");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn’t send. Please email us instead.");
      setState("idle");
    }
  };
  if (state === "sent") return <p className="text-[14px] text-text">Received. We’ll reply by {due}, and we’ve emailed you a reference.</p>;
  return (
    <form onSubmit={submit} className="space-y-3">
      <label className="block text-[13px] font-medium text-text">
        Your email
        <input name="email" type="email" required autoComplete="email" className="mt-1 h-11 w-full rounded-[var(--radius-control)] border border-border bg-surface px-3 text-[15px] font-normal" />
      </label>
      <label className="block text-[13px] font-medium text-text">
        Your request or complaint
        <textarea name="details" required minLength={10} maxLength={4000} rows={4} className="mt-1 w-full rounded-[var(--radius-control)] border border-border bg-surface px-3 py-2 text-[15px] font-normal" />
      </label>
      {error && (
        <p role="alert" className="text-[13px] text-[var(--error)]">
          {error}
        </p>
      )}
      <Button type="submit" loading={state === "sending"}>
        Send
      </Button>
    </form>
  );
}

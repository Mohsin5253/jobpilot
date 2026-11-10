"use client";

import { MailCheck } from "lucide-react";
import { useState, type FormEvent } from "react";

import { AuthCard } from "@/components/auth-card";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/input";
import { api, ApiError } from "@/lib/api";

export default function ForgotPasswordPage() {
  const [sent, setSent] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      await api.post("/auth/forgot-password", { email: new FormData(e.currentTarget).get("email") });
      setSent(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong");
    } finally {
      setLoading(false);
    }
  };

  if (sent) {
    return (
      <AuthCard title="Check your inbox" description="If that email has an account, we’ve sent a link to reset your password. It works once, for one hour.">
        <div className="grid place-items-center py-2 text-success">
          <MailCheck className="size-10" />
        </div>
      </AuthCard>
    );
  }
  return (
    <AuthCard title="Reset your password" description="Enter your account email and we’ll send you a reset link.">
      <form onSubmit={submit} className="space-y-4">
        <Field label="Email">
          <Input name="email" type="email" required autoComplete="email" placeholder="you@college.edu" />
        </Field>
        {error && <p className="rounded-lg border border-danger/20 bg-danger/10 px-3 py-2 text-[13px] text-danger">{error}</p>}
        <Button type="submit" variant="primary" className="w-full" loading={loading}>
          Send reset link
        </Button>
      </form>
    </AuthCard>
  );
}

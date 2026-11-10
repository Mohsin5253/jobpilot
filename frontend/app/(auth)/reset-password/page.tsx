"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState, type FormEvent } from "react";

import { AuthCard } from "@/components/auth-card";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/input";
import { api, ApiError } from "@/lib/api";

function ResetForm() {
  const router = useRouter();
  const token = useSearchParams().get("token") ?? "";
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const fd = new FormData(e.currentTarget);
    if (fd.get("password") !== fd.get("confirm")) {
      setError("The two passwords don’t match");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      await api.post("/auth/reset-password", { token, password: fd.get("password") });
      router.replace("/dashboard");
      router.refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong");
      setLoading(false);
    }
  };

  if (!token) {
    return <AuthCard title="Link incomplete" description="Open the reset link from your email again, or ask for a new one." >{null}</AuthCard>;
  }
  return (
    <AuthCard title="Choose a new password" description="You’ll be signed out everywhere else.">
      <form onSubmit={submit} className="space-y-4">
        <Field label="New password" hint="At least 8 characters">
          <Input name="password" type="password" required minLength={8} autoComplete="new-password" />
        </Field>
        <Field label="Confirm password">
          <Input name="confirm" type="password" required minLength={8} autoComplete="new-password" />
        </Field>
        {error && <p className="rounded-lg border border-danger/20 bg-danger/10 px-3 py-2 text-[13px] text-danger">{error}</p>}
        <Button type="submit" variant="primary" className="w-full" loading={loading}>
          Set password and sign in
        </Button>
      </form>
    </AuthCard>
  );
}

export default function ResetPasswordPage() {
  return (
    <Suspense>
      <ResetForm />
    </Suspense>
  );
}

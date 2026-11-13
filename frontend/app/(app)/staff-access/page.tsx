"use client";

import { useMutation } from "@tanstack/react-query";
import { ShieldCheck } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { Field, Input } from "@/components/ui/input";
import { api, ApiError } from "@/lib/api";

type Structure = { campus: string; departments: { id: string; name: string }[]; programs: { id: string; department_id: string; name: string }[]; batches: { id: string; program_id: string; name: string }[] };

export default function StaffAccessPage() {
  return (
    <Suspense>
      <StaffAccess />
    </Suspense>
  );
}

/** Opening the Campus portal: approved staff only; TPOs and Principals confirm a code sent to their email (2FA).
 * Staff who aren't members yet join here: staff code + institutional email + approval by the TPO. */
function StaffAccess() {
  const router = useRouter();
  const next = useSearchParams().get("next") || "/campus";
  const [state, setState] = useState<"checking" | "otp" | "notstaff" | "pending">("checking");
  const [otp, setOtp] = useState("");
  const open = useMutation({
    mutationFn: (code?: string) => api.post("/campus/staff-session", code ? { otp: code } : {}),
    onSuccess: () => router.replace(next),
    onError: (e: Error) => toast.error(e.message),
  });
  useEffect(() => {
    api.post<{ needed: boolean }>("/campus/staff-session/otp", {}).then(
      (r) => (r.needed ? setState("otp") : open.mutate(undefined)),
      (e: ApiError) => setState(e.status === 403 && /waiting/i.test(e.message) ? "pending" : "notstaff"),
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return (
    <div className="mx-auto max-w-xl space-y-6">
      <Card>
        <CardHeader icon={<ShieldCheck className="size-4" />} title="Campus portal" description="For verified college staff: TPOs, principals, HODs, faculty and placement coordinators." />
        <div className="space-y-3 p-5 text-[14px]">
          {state === "checking" && <p className="text-text-2">Checking your staff access…</p>}
          {state === "otp" && (
            <form onSubmit={(e) => (e.preventDefault(), open.mutate(otp))} className="space-y-2">
              <p className="text-text-2">We emailed you a 6-digit code (two-step sign-in for TPOs and principals).</p>
              <div className="flex gap-2">
                <Input inputMode="numeric" maxLength={6} value={otp} onChange={(e) => setOtp(e.target.value.replace(/\D/g, ""))} placeholder="6-digit code" aria-label="Code" />
                <Button type="submit" variant="primary" loading={open.isPending} disabled={otp.length !== 6}>Open</Button>
              </div>
            </form>
          )}
          {state === "pending" && <p className="text-text-2">Your staff account is waiting for your TPO or Principal to approve it. You'll get a notification.</p>}
          {state === "notstaff" && (
            <p className="text-text-2">
              The Campus portal is for approved college staff. Students: your college, internships, roles and awards are in{" "}
              <Link href="/campus-profile" className="font-medium text-cobalt-text hover:underline">Campus profile</Link>.
            </p>
          )}
        </div>
      </Card>
      {(state === "notstaff" || state === "pending") && state === "notstaff" && <JoinAsStaff />}
    </div>
  );
}

function JoinAsStaff() {
  const [code, setCode] = useState("");
  const [email, setEmail] = useState("");
  const [s, setS] = useState<Structure | null>(null);
  const [otp, setOtp] = useState("");
  const [role, setRole] = useState("faculty");
  const [depts, setDepts] = useState<string[]>([]);
  const [batches, setBatches] = useState<string[]>([]);
  const start = useMutation({ mutationFn: () => api.post<Structure>("/campus/staff-join/start", { code, email }), onSuccess: setS, onError: (e: Error) => toast.error(e.message) });
  const verify = useMutation({
    mutationFn: () => api.post<{ detail: string }>("/campus/staff-join/verify", { otp, role, department_ids: depts, batch_ids: batches }),
    onSuccess: (r) => toast.success(r.detail, { duration: 10000 }),
    onError: (e: Error) => toast.error(e.message),
  });
  return (
    <Card>
      <CardHeader title="Join your college as staff" description="Your TPO gives you the staff code. Use your institutional email: personal addresses (Gmail, Yahoo, Outlook…) aren't accepted." />
      <div className="space-y-3 p-5">
        {!s ? (
          <form onSubmit={(e) => (e.preventDefault(), start.mutate())} className="space-y-3">
            <Field label="Staff code"><Input value={code} onChange={(e) => setCode(e.target.value)} placeholder="STAFF-XXXX-XXXX-XXXX" /></Field>
            <Field label="Institutional email"><Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@college.edu.in" /></Field>
            <Button type="submit" loading={start.isPending} disabled={code.length < 6 || !email.includes("@")}>Send code</Button>
          </form>
        ) : (
          <form onSubmit={(e) => (e.preventDefault(), verify.mutate())} className="space-y-3">
            <p className="text-[13.5px]">Joining <b>{s.campus}</b>. Enter the code sent to {email}.</p>
            <Input inputMode="numeric" maxLength={6} value={otp} onChange={(e) => setOtp(e.target.value.replace(/\D/g, ""))} placeholder="6-digit code" aria-label="Code" />
            <Field label="Your role">
              <select value={role} onChange={(e) => setRole(e.target.value)} className="h-10 w-full rounded-[var(--radius-control)] border border-border bg-surface px-3 text-[13px]">
                <option value="faculty">Faculty / teacher</option><option value="hod">Head of department</option><option value="coordinator">Placement coordinator</option>
              </select>
            </Field>
            <Field label="Department(s)">
              <select multiple value={depts} onChange={(e) => setDepts(Array.from(e.target.selectedOptions).map((o) => o.value))} className="h-28 w-full rounded-[var(--radius-control)] border border-border bg-surface px-3 text-[13px]">
                {s.departments.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
              </select>
            </Field>
            {role === "faculty" && !!s.batches.length && (
              <Field label="Batches you teach (optional)">
                <select multiple value={batches} onChange={(e) => setBatches(Array.from(e.target.selectedOptions).map((o) => o.value))} className="h-28 w-full rounded-[var(--radius-control)] border border-border bg-surface px-3 text-[13px]">
                  {s.batches.filter((b) => !depts.length || s.programs.some((p) => p.id === b.program_id && depts.includes(p.department_id))).map((b) => <option key={b.id} value={b.id}>{s.programs.find((p) => p.id === b.program_id)?.name} · {b.name}</option>)}
                </select>
              </Field>
            )}
            <Button type="submit" variant="primary" loading={verify.isPending} disabled={otp.length !== 6}>Ask to join</Button>
          </form>
        )}
      </div>
    </Card>
  );
}

"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { ShieldCheck } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { Field, Input } from "@/components/ui/input";
import { api, ApiError } from "@/lib/api";
import { useMe } from "@/lib/queries";

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
  const params = useSearchParams();
  const next = params.get("next") || "/campus";
  const campus = params.get("campus");
  const target = campus ? { campus_id: campus } : {};
  const [state, setState] = useState<"checking" | "otp" | "notstaff" | "pending" | "noemail">("checking");
  const [otp, setOtp] = useState("");
  const isAdmin = !!useMe().data?.is_admin;
  const open = useMutation({
    mutationFn: (code?: string) => api.post("/campus/staff-session", code ? { ...target, otp: code } : target),
    onSuccess: () => router.replace(next),
    onError: (e: Error) => toast.error(e.message),
  });
  useEffect(() => {
    api.post<{ needed: boolean }>("/campus/staff-session/otp", target).then(
      (r) => (r.needed ? setState("otp") : open.mutate(undefined)),
      (e: ApiError) => setState(e.status === 503 ? "noemail" : e.status === 403 && /waiting/i.test(e.message) ? "pending" : "notstaff"),
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
          {state === "noemail" && (
            <p className="text-text-2">You're staff here, but your two-step sign-in code couldn't be emailed: email isn't set up on this server yet. Ask JobPilot support to switch it on.</p>
          )}
          {state === "pending" && <p className="text-text-2">Your staff account is waiting for approval by your TPO, Principal or (for a department's own code) its HOD. You'll get a notification.</p>}
          {state === "notstaff" && isAdmin && (
            <p className="text-text-2">
              You're a JobPilot admin but not staff at a college, so the portal has no students to show you. Create colleges, appoint TPOs and verify departments in{" "}
              <Link href="/admin" className="font-medium text-cobalt-text hover:underline">Admin</Link>.
            </p>
          )}
          {state === "notstaff" && !isAdmin && (
            <p className="text-text-2">
              The Campus portal is for approved college staff. Students: your college, internships, roles and awards are in{" "}
              <Link href="/campus-profile" className="font-medium text-cobalt-text hover:underline">Campus profile</Link>.
            </p>
          )}
        </div>
      </Card>
      {state === "notstaff" && <JoinAsStaff />}
      {(state === "notstaff" || state === "pending") && <RegisterDepartment />}
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
            {s.departments.length === 1 && <p className="text-[12.5px] text-text-3">This is a department's own code: you join {s.departments[0].name} only, and its HOD approves you.</p>}
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

type Inst = { aishe_id: string; name: string; state: string; district: string };
type DeptReq = { id: string; college_name: string; branch: string; department_name: string; status: "pending" | "approved" | "rejected"; reason: string | null };

/** Department plan: an HOD registers their own department (up to 300 students). Institutional email first, then a
 * JobPilot check that the department really belongs to the college; then it opens here. */
function RegisterDepartment() {
  const [q, setQ] = useState("");
  const [inst, setInst] = useState<Inst | null>(null);
  const [college, setCollege] = useState("");
  const [branch, setBranch] = useState("");
  const [dept, setDept] = useState("");
  const [city, setCity] = useState("");
  const [email, setEmail] = useState("");
  const [otp, setOtp] = useState("");
  const [sent, setSent] = useState(false);
  const mine = useQuery({ queryKey: ["dept-requests-mine"], queryFn: () => api.get<DeptReq[]>("/campus/department-requests/mine") });
  const found = useQuery({ queryKey: ["aishe", q], queryFn: () => api.get<Inst[]>(`/campus/institutions/search?q=${encodeURIComponent(q)}`), enabled: q.trim().length >= 3 && !inst });
  const start = useMutation({
    mutationFn: () => api.post("/campus/department-requests/start", { aishe_id: inst?.aishe_id ?? null, college_name: inst ? inst.name : college, branch, department_name: dept, city: inst?.district ?? city, state: inst?.state ?? "", email }),
    onSuccess: () => setSent(true),
    onError: (e: Error) => toast.error(e.message),
  });
  const verify = useMutation({
    mutationFn: () => api.post("/campus/department-requests/verify", { otp }),
    onSuccess: () => (toast.success("Email confirmed. We'll verify your department and notify you."), setSent(false), setOtp(""), mine.refetch()),
    onError: (e: Error) => toast.error(e.message),
  });
  const latest = mine.data?.[0];
  return (
    <Card>
      <CardHeader title="Register your department" description="Department plan: one department (for example Computer Science), up to 300 students, unlimited staff. You become its HOD once we've verified it." />
      <div className="space-y-3 p-5 text-[14px]">
        {latest && (
          <p className={latest.status === "rejected" ? "text-[var(--error)]" : "text-text-2"}>
            {latest.department_name}, {latest.college_name}{latest.branch ? ` — ${latest.branch}` : ""}:{" "}
            {latest.status === "pending" ? "waiting for verification." : latest.status === "approved" ? "verified. Reload this page to open the portal." : `not approved: ${latest.reason}`}
          </p>
        )}
        {latest?.status === "pending" ? null : !sent ? (
          <form onSubmit={(e) => (e.preventDefault(), start.mutate())} className="space-y-3">
            <Field label="College">
              {inst ? (
                <div className="flex items-center justify-between gap-2 rounded-[var(--radius-control)] border border-border px-3 py-2 text-[13px]">
                  <span>{inst.name} · {inst.district}, {inst.state}</span>
                  <button type="button" onClick={() => setInst(null)} className="text-text-3 hover:text-text">Change</button>
                </div>
              ) : (
                <Input value={q} onChange={(e) => (setQ(e.target.value), setCollege(e.target.value))} placeholder="Search the AISHE list, or type your college's full name" />
              )}
            </Field>
            {!inst && !!found.data?.length && (
              <div className="max-h-44 divide-y divide-border overflow-y-auto rounded-[var(--radius-control)] border border-border">
                {found.data.map((i) => (
                  <button key={i.aishe_id} type="button" onClick={() => setInst(i)} className="block w-full px-3 py-2 text-left text-[13px] hover:bg-elevated">
                    {i.name} <span className="text-text-3">· {i.district}, {i.state}</span>
                  </button>
                ))}
              </div>
            )}
            {!inst && <Field label="City"><Input value={city} onChange={(e) => setCity(e.target.value)} placeholder="Pune" /></Field>}
            <Field label="Branch (if your college has several, e.g. Engineering or Law)"><Input value={branch} onChange={(e) => setBranch(e.target.value)} placeholder="Engineering" /></Field>
            <Field label="Department name"><Input value={dept} onChange={(e) => setDept(e.target.value)} placeholder="Computer Science" /></Field>
            <Field label="Your institutional email"><Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="hod.cs@college.edu.in" /></Field>
            <Button type="submit" loading={start.isPending} disabled={dept.trim().length < 2 || !email.includes("@") || !(inst || college.trim().length >= 3)}>Send code</Button>
          </form>
        ) : (
          <form onSubmit={(e) => (e.preventDefault(), verify.mutate())} className="space-y-2">
            <p className="text-text-2">Enter the 6-digit code we sent to {email}.</p>
            <div className="flex gap-2">
              <Input inputMode="numeric" maxLength={6} value={otp} onChange={(e) => setOtp(e.target.value.replace(/\D/g, ""))} placeholder="6-digit code" aria-label="Code" />
              <Button type="submit" variant="primary" loading={verify.isPending} disabled={otp.length !== 6}>Confirm</Button>
            </div>
          </form>
        )}
      </div>
    </Card>
  );
}

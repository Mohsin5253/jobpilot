"use client";

import { useQueryClient } from "@tanstack/react-query";
import { FileUp, Users } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { Input, Textarea } from "@/components/ui/input";
import { api } from "@/lib/api";

type Parsed = {
  company: string;
  role: string;
  kind: "internship" | "full_time";
  compensation: string;
  eligibility: { min_cgpa?: number; min_percent?: number; branches?: string[]; max_backlogs?: number; grad_years?: number[] };
  register_by: string | null;
  rounds: { name: string; type: string }[];
};

/** Placement cell: paste a circular (or upload the PDF), check what we read, post it to eligible students. */
export function CircularImport() {
  const qc = useQueryClient();
  const [text, setText] = useState("");
  const [p, setP] = useState<Parsed | null>(null);
  const [busy, setBusy] = useState(false);
  const parse = async (file?: File) => {
    setBusy(true);
    try {
      if (file) {
        const fd = new FormData();
        fd.set("file", file);
        fd.set("text", text);
        const r = await fetch("/api/college/drives/parse", { method: "POST", body: fd });
        if (!r.ok) throw new Error((await r.json()).detail ?? "Couldn’t read that file");
        setP(await r.json());
      } else setP(await api.post<Parsed>("/college/drives/parse", { text }));
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Couldn’t read that circular");
    } finally {
      setBusy(false);
    }
  };
  const post = async () => {
    if (!p) return;
    setBusy(true);
    try {
      const { min_percent: _, ...elig } = p.eligibility;
      const r = await api.post<{ notified: number }>("/college/drives", {
        company: p.company, role: p.role, kind: p.kind, compensation: p.compensation, eligibility: elig,
        register_by: p.register_by ? `${p.register_by}T18:29:00Z` : null, rounds: p.rounds.map((x) => ({ name: x.name, type: x.type })), notes: text.slice(0, 4000),
      });
      toast.success(`Posted. ${r.notified} eligible student${r.notified === 1 ? "" : "s"} notified.`);
      setP(null);
      setText("");
      qc.invalidateQueries();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Couldn’t post the drive");
    } finally {
      setBusy(false);
    }
  };
  const set = (k: keyof Parsed, v: string) => p && setP({ ...p, [k]: v });
  return (
    <Card>
      <CardHeader icon={<FileUp className="size-4" />} title="Post a drive from a circular" description="Paste the WhatsApp message or upload the PDF. Check the details, then post: eligible students who share with the college are notified." />
      <div className="space-y-3 p-5">
        <Textarea value={text} onChange={(e) => setText(e.target.value)} rows={5} placeholder="Paste the circular here…" />
        <div className="flex flex-wrap gap-2">
          <Button onClick={() => parse()} loading={busy && !p} disabled={!text.trim()}>
            Read circular
          </Button>
          <label className="inline-flex h-10 cursor-pointer items-center rounded-[var(--radius-control)] border border-border px-3 text-[13px] text-text-2">
            Upload PDF
            <input type="file" accept=".pdf,.txt" className="sr-only" onChange={(e) => e.target.files?.[0] && parse(e.target.files[0])} />
          </label>
        </div>
        {p && (
          <div className="space-y-2 rounded-[var(--radius-card)] border border-border p-4 text-[13px]">
            <div className="grid gap-2 sm:grid-cols-2">
              <Input value={p.company} onChange={(e) => set("company", e.target.value)} aria-label="Company" />
              <Input value={p.role} onChange={(e) => set("role", e.target.value)} aria-label="Role" />
              <Input value={p.compensation} onChange={(e) => set("compensation", e.target.value)} aria-label="CTC or stipend" />
              <Input value={p.register_by ?? ""} onChange={(e) => set("register_by", e.target.value)} aria-label="Register by (YYYY-MM-DD)" placeholder="YYYY-MM-DD" />
            </div>
            <div className="flex flex-wrap gap-1.5">
              {p.eligibility.min_cgpa != null && <Badge>CGPA ≥ {p.eligibility.min_cgpa}</Badge>}
              {p.eligibility.min_percent != null && <Badge>{p.eligibility.min_percent}%</Badge>}
              <Badge>{p.eligibility.branches?.length ? p.eligibility.branches.join(", ") : "All branches"}</Badge>
              {p.eligibility.max_backlogs != null && <Badge>Backlogs ≤ {p.eligibility.max_backlogs}</Badge>}
              {!!p.eligibility.grad_years?.length && <Badge>Batch {p.eligibility.grad_years.join(", ")}</Badge>}
              {p.rounds.map((r) => (
                <Badge key={r.name} tone="outline">
                  {r.name}
                </Badge>
              ))}
            </div>
            <Button variant="primary" onClick={post} loading={busy} disabled={!p.company || !p.role}>
              Post drive
            </Button>
          </div>
        )}
      </div>
    </Card>
  );
}

/** Placement cell: alumni who agreed to be asked for referrals (CSV; rows without consent are dropped). */
export function AlumniUpload() {
  const [csv, setCsv] = useState("name,company,role,batch,contact,consent\n");
  const [busy, setBusy] = useState(false);
  const upload = async () => {
    setBusy(true);
    try {
      const r = await api.post<{ added: number; skipped_without_consent: number }>("/college/alumni", { csv });
      toast.success(`${r.added} alumni added · ${r.skipped_without_consent} skipped (no consent)`);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Upload failed");
    } finally {
      setBusy(false);
    }
  };
  return (
    <Card>
      <CardHeader icon={<Users className="size-4" />} title="Alumni for referrals" description="Only alumni who agreed to be contacted. Columns: name, company, role, batch, contact, consent (yes/no)." />
      <div className="space-y-3 p-5">
        <Textarea value={csv} onChange={(e) => setCsv(e.target.value)} rows={5} className="font-mono text-[12.5px]" />
        <Button onClick={upload} loading={busy}>
          Upload
        </Button>
      </div>
    </Card>
  );
}

/** Students: alumni of your college at a company, who agreed to help. */
export function AlumniLookup() {
  const [company, setCompany] = useState("");
  const [rows, setRows] = useState<{ name: string; role: string; batch: number | null; contact: string }[] | null>(null);
  const find = async () => setRows(await api.get(`/campus/alumni?company=${encodeURIComponent(company)}`));
  return (
    <Card>
      <CardHeader icon={<Users className="size-4" />} title="Alumni who can refer you" description="From your college, only alumni who agreed to be asked." />
      <div className="space-y-3 p-5">
        <div className="flex gap-2">
          <Input value={company} onChange={(e) => setCompany(e.target.value)} placeholder="Company" className="flex-1" />
          <Button onClick={find} disabled={company.trim().length < 2}>
            Find
          </Button>
        </div>
        {rows && !rows.length && <p className="text-[13px] text-subtle">No consenting alumni at {company} yet.</p>}
        {rows?.map((a) => (
          <div key={a.name + a.contact} className="text-[13.5px]">
            <b>{a.name}</b> · {a.role} {a.batch ? `· ${a.batch}` : ""}{" "}
            {a.contact && (
              <a href={a.contact.startsWith("http") ? a.contact : `mailto:${a.contact}`} className="text-accent hover:underline" target="_blank" rel="noreferrer">
                contact
              </a>
            )}
          </div>
        ))}
      </div>
    </Card>
  );
}

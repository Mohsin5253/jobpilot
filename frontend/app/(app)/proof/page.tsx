"use client";

import { BadgeCheck, Copy, ExternalLink, Github, Link2, Plus, Trash2, Trophy } from "lucide-react";
import { useState, type FormEvent } from "react";
import { toast } from "sonner";

import { ProofView } from "@/components/proof-card";
import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { Field, Input, Switch } from "@/components/ui/input";
import { EmptyState, PageHeader, Skeleton } from "@/components/ui/misc";
import {
  useProofLinks,
  useRevokeProofLink,
  useAddEvidenceItem,
  useEvidence,
  useLinkCodeforces,
  useLinkGithub,
  useMe,
  usePublishProof,
  useRemoveEvidenceItem,
  useUnlinkEvidence,
  useVerifyGithub,
} from "@/lib/queries";

export default function ProofPage() {
  const { data: me } = useMe();
  const { data: ev, isLoading } = useEvidence();
  const linkGh = useLinkGithub();
  const verify = useVerifyGithub();
  const linkCf = useLinkCodeforces();
  const unlink = useUnlinkEvidence();
  const addItem = useAddEvidenceItem();
  const removeItem = useRemoveEvidenceItem();
  const publish = usePublishProof();
  const [gh, setGh] = useState("");
  const [cf, setCf] = useState("");

  if (isLoading || !ev) return <Skeleton agent="tailor" className="min-h-96" />;
  const url = ev.slug && typeof window !== "undefined" ? `${window.location.origin}/p/${ev.slug}` : null;
  const demo = !!me?.is_demo;

  const add = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const form = e.currentTarget;
    const fd = new FormData(form);
    addItem.mutate({ kind: String(fd.get("kind")), title: String(fd.get("title")), url: String(fd.get("url")) }, { onSuccess: () => form.reset() });
  };

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Proof of skills"
        title="Your proof pack"
        description="Recruiters now see about 244 applications per role (Greenhouse, 2026). Evidence they can click stands out, and it’s linked in every application JobPilot drafts for you."
      />

      <ProofLinksCard />

      <div className="grid gap-6 xl:grid-cols-[1fr_1.15fr] [&>*]:min-w-0">
        <div className="space-y-6">
          <Card>
            <CardHeader icon={<Github className="size-4" />} title="GitHub" description="Public repos, languages and recent activity, read from GitHub’s official API." />
            <div className="space-y-4 p-5">
              {ev.github ? (
                <div className="flex flex-wrap items-center justify-between gap-3 rounded-[var(--radius-card)] border border-border px-4 py-3">
                  <div>
                    <div className="text-[14px] font-medium">@{ev.github.username}</div>
                    <div className="text-[12px] text-subtle">
                      {ev.github.public_repos} repos · {ev.github.stars} stars · {ev.github.verified ? "ownership verified" : "not verified yet"}
                    </div>
                  </div>
                  <Button size="sm" variant="ghost" onClick={() => unlink.mutate("github")} disabled={demo}>
                    Unlink
                  </Button>
                </div>
              ) : (
                <form onSubmit={(e) => (e.preventDefault(), linkGh.mutate(gh))} className="flex gap-2">
                  <Input value={gh} onChange={(e) => setGh(e.target.value)} placeholder="your-github-username" disabled={demo} />
                  <Button type="submit" variant="primary" loading={linkGh.isPending} disabled={demo || !gh.trim()}>
                    Link
                  </Button>
                </form>
              )}
              {ev.github && !ev.github.verified && ev.verify_code && (
                <div className="rounded-[var(--radius-card)] border border-border-strong bg-accent-soft p-4 text-[13px] leading-relaxed">
                  <b>Verify it’s yours:</b> add <code className="num rounded-[4px] bg-surface px-1.5 py-0.5 text-cobalt-text">{ev.verify_code}</code> anywhere in your{" "}
                  <a href="https://github.com/settings/profile" target="_blank" rel="noreferrer" className="text-accent underline">
                    GitHub bio
                  </a>
                  , save, then press verify. You can remove it afterwards.
                  <div className="mt-3 flex gap-2">
                    <Button size="sm" onClick={() => (navigator.clipboard.writeText(ev.verify_code!), toast.success("Copied"))}>
                      <Copy className="size-3.5" /> Copy code
                    </Button>
                    <Button size="sm" variant="primary" onClick={() => verify.mutate(undefined)} loading={verify.isPending}>
                      <BadgeCheck className="size-3.5" /> Verify
                    </Button>
                  </div>
                </div>
              )}
            </div>
          </Card>

          <Card>
            <CardHeader icon={<Trophy className="size-4" />} title="Codeforces" description="Rating and rank from the official Codeforces API." />
            <div className="p-5">
              {ev.codeforces ? (
                <div className="flex items-center justify-between rounded-[var(--radius-card)] border border-border px-4 py-3">
                  <div className="text-[14px]">
                    <b>{ev.codeforces.handle}</b> · {ev.codeforces.rating ?? "unrated"} <span className="text-subtle capitalize">({ev.codeforces.rank})</span>
                  </div>
                  <Button size="sm" variant="ghost" onClick={() => unlink.mutate("codeforces")} disabled={demo}>
                    Unlink
                  </Button>
                </div>
              ) : (
                <form onSubmit={(e) => (e.preventDefault(), linkCf.mutate(cf))} className="flex gap-2">
                  <Input value={cf} onChange={(e) => setCf(e.target.value)} placeholder="handle" disabled={demo} />
                  <Button type="submit" loading={linkCf.isPending} disabled={demo || !cf.trim()}>
                    Link
                  </Button>
                </form>
              )}
            </div>
          </Card>

          <Card>
            <CardHeader icon={<Link2 className="size-4" />} title="Projects, certificates & profiles" description="LeetCode, Kaggle, hackathons, deployed apps. Shown as self-reported; we check the link is live." />
            <div className="space-y-3 p-5">
              {ev.items.map((i) => (
                <div key={i.id} className="flex items-center gap-3 rounded-[var(--radius-card)] border border-border px-4 py-2.5">
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-[13.5px] font-medium">{i.title}</div>
                    <div className="truncate text-[12px] text-subtle">
                      {i.kind} · {i.live === false ? "link looks dead" : "link live"} · {i.url}
                    </div>
                  </div>
                  <button type="button" aria-label={`Remove ${i.title}`} onClick={() => removeItem.mutate(i.id)} className="grid size-11 shrink-0 place-items-center rounded-[var(--radius-control)] text-text-3 hover:bg-[color-mix(in_oklab,var(--error)_10%,transparent)] hover:text-[var(--error)] md:size-8">
                    <Trash2 className="size-4" />
                  </button>
                </div>
              ))}
              <form onSubmit={add} className="grid gap-2 sm:grid-cols-[130px_1fr]">
                <select name="kind" className="h-11 rounded-[var(--radius-control)] border border-border bg-surface px-3 text-[14px] text-text md:h-9" aria-label="Kind" disabled={demo}>
                  <option value="project">Live project</option>
                  <option value="leetcode">LeetCode</option>
                  <option value="kaggle">Kaggle</option>
                  <option value="certificate">Certificate</option>
                  <option value="hackathon">Hackathon</option>
                  <option value="other">Other</option>
                </select>
                <Input name="title" required placeholder="What is it? e.g. RAG search demo" disabled={demo} />
                <Input name="url" required type="url" placeholder="https://…" className="sm:col-span-2" disabled={demo} />
                <Button type="submit" className="sm:col-span-2" loading={addItem.isPending} disabled={demo}>
                  <Plus className="size-4" /> Add to proof pack
                </Button>
              </form>
            </div>
          </Card>

          <Card>
            <CardHeader title="Public proof page" description="A link recruiters can open: evidence only, never your email or phone. Added to every draft while it’s published." />
            <div className="space-y-3 p-5">
              <div className="flex items-center justify-between rounded-[var(--radius-card)] border border-border px-4 py-3">
                <div className="text-[13.5px] font-medium">Publish my proof page</div>
                <Switch checked={ev.public} onChange={(v) => !demo && publish.mutate(v)} label="Publish proof page" />
              </div>
              {url && (
                <div className="flex items-center gap-2">
                  <Input readOnly value={url} />
                  <Button size="icon" onClick={() => (navigator.clipboard.writeText(url), toast.success("Link copied"))} aria-label="Copy link">
                    <Copy className="size-4" />
                  </Button>
                  <a href={url} target="_blank" rel="noreferrer" className="grid size-11 shrink-0 place-items-center rounded-[var(--radius-control)] border border-border hover:border-border-strong md:size-9" aria-label="Open the public proof page">
                    <ExternalLink className="size-4" />
                  </a>
                </div>
              )}
              {demo && <p className="text-[12.5px] text-subtle">Linking accounts is turned off in the demo.</p>}
            </div>
          </Card>
        </div>

        <div>
          <div className="eyebrow mb-3">Preview · what recruiters see</div>
          {ev.github || ev.codeforces || ev.items.length ? (
            <ProofView proof={{ name: "", headline: "", github: ev.github, codeforces: ev.codeforces, items: ev.items.filter((i) => i.live !== false), skills: ev.skills }} />
          ) : (
            <div className="card">
              <EmptyState agent="tailor" />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}


/** One signed link per approved application: who opened it, and a way to withdraw it. */
function ProofLinksCard() {
  const { data } = useProofLinks();
  const revoke = useRevokeProofLink();
  if (!data?.length) return null;
  return (
    <Card>
      <CardHeader icon={<Link2 className="size-4" />} title="Proof Links in your applications" description="Each approved application carries its own signed link. Opens are counted on our server; no tracking pixels." />
      <ul className="divide-y divide-border">
        {data.map((l) => (
          <li key={l.id} className="flex flex-wrap items-center justify-between gap-3 px-5 py-3">
            <div className="min-w-0">
              <div className="truncate text-[13.5px] font-medium">
                {l.company} · {l.role}
              </div>
              <div className="text-[12px] text-subtle">
                {l.revoked_at ? "Revoked" : l.views ? `Opened ${l.views}× · last ${new Date(l.last_viewed_at ?? "").toLocaleDateString("en-IN")}` : "Not opened yet"}
              </div>
            </div>
            {!l.revoked_at && (
              <div className="flex gap-2">
                <Button size="sm" variant="ghost" onClick={() => navigator.clipboard.writeText(l.url).then(() => toast.success("Link copied"))}>
                  <Copy /> Copy
                </Button>
                <Button size="sm" variant="danger" onClick={() => revoke.mutate(l.id)}>
                  Revoke
                </Button>
              </div>
            )}
          </li>
        ))}
      </ul>
    </Card>
  );
}

import { BadgeCheck, ExternalLink, Star } from "lucide-react";

import type { PublicProof } from "@/lib/types";

const KIND: Record<string, string> = { leetcode: "LeetCode", kaggle: "Kaggle", certificate: "Certificate", project: "Live project", hackathon: "Hackathon", other: "Link" };

/** The proof page body, shared by the owner's preview and the public /p/[slug] page. */
export function ProofView({ proof }: { proof: PublicProof }) {
  const gh = proof.github;
  return (
    <div className="space-y-6">
      {!!proof.skills.length && (
        <div className="card p-6">
          <div className="eyebrow mb-3">Skills backed by evidence</div>
          <div className="flex flex-wrap gap-2">
            {proof.skills.map((s) => (
              <span key={s} className="inline-flex items-center gap-1.5 rounded-full border border-border-strong bg-accent-soft px-3 py-1 text-[13px]">
                <BadgeCheck className="size-3.5 text-accent" /> {s}
              </span>
            ))}
          </div>
        </div>
      )}
      {gh && (
        <div className="card p-6">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <div className="eyebrow">GitHub</div>
              <a href={gh.url} target="_blank" rel="noreferrer" className="mt-1 inline-flex items-center gap-1.5 font-display text-[28px] hover:underline">
                @{gh.username} <ExternalLink className="size-4 text-subtle" />
              </a>
            </div>
            {gh.verified ? (
              <span className="inline-flex items-center gap-1.5 rounded-full foil px-3 py-1 text-[12px] font-semibold">
                <BadgeCheck className="size-3.5" /> Ownership verified
              </span>
            ) : (
              <span className="rounded-full border border-border px-3 py-1 text-[12px] text-subtle">Linked, not verified</span>
            )}
          </div>
          <div className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-4">
            {[
              ["Original repos", gh.public_repos],
              ["Stars earned", gh.stars],
              ["Active in 90 days", gh.active_repos_90d],
              ["On GitHub since", gh.since?.slice(0, 4) || "—"],
            ].map(([k, v]) => (
              <div key={k as string} className="rounded-[var(--radius-card)] border border-border bg-surface-2/50 p-3.5">
                <div className="text-[11.5px] text-subtle">{k}</div>
                <div className="mt-1 font-display text-[28px] leading-none">{v}</div>
              </div>
            ))}
          </div>
          {!!Object.keys(gh.languages).length && (
            <div className="mt-4 flex flex-wrap gap-1.5">
              {Object.entries(gh.languages).map(([l, n]) => (
                <span key={l} className="rounded-md border border-border px-2 py-0.5 text-[12px] text-muted">
                  {l} · {n}
                </span>
              ))}
            </div>
          )}
          <div className="mt-5 grid gap-3 md:grid-cols-2">
            {gh.top_repos.map((r) => (
              <a key={r.url} href={r.url} target="_blank" rel="noreferrer" className="group rounded-[var(--radius-card)] border border-border p-4 transition-colors hover:border-border-strong">
                <div className="flex items-center justify-between gap-2">
                  <span className="truncate text-[14.5px] font-medium group-hover:text-accent">{r.name}</span>
                  <span className="inline-flex items-center gap-1 text-[12px] text-subtle">
                    <Star className="size-3" /> {r.stars}
                  </span>
                </div>
                {r.description && <p className="mt-1 line-clamp-2 text-[13px] text-muted">{r.description}</p>}
                <div className="mt-2 text-[11.5px] text-subtle">
                  {[r.language, ...r.topics.slice(0, 3)].filter(Boolean).join(" · ")} · updated {r.pushed_at}
                </div>
              </a>
            ))}
          </div>
        </div>
      )}
      {(proof.codeforces || proof.items.length > 0) && (
        <div className="card p-6">
          <div className="eyebrow mb-3">Competitive programming & more</div>
          <div className="grid gap-3 md:grid-cols-2">
            {proof.codeforces && (
              <a href={proof.codeforces.url} target="_blank" rel="noreferrer" className="rounded-[var(--radius-card)] border border-border p-4 hover:border-border-strong">
                <div className="text-[12px] text-subtle">Codeforces · linked</div>
                <div className="mt-1 font-display text-[28px] leading-none">{proof.codeforces.rating ?? "Unrated"}</div>
                <div className="mt-1 text-[12.5px] text-muted capitalize">
                  {proof.codeforces.rank}
                  {proof.codeforces.max_rating ? ` · best ${proof.codeforces.max_rating}` : ""}
                </div>
              </a>
            )}
            {proof.items.map((i) => (
              <a key={i.id} href={i.url} target="_blank" rel="noreferrer" className="rounded-[var(--radius-card)] border border-border p-4 hover:border-border-strong">
                <div className="text-[12px] text-subtle">
                  {KIND[i.kind] ?? "Link"} · self-reported{i.live ? " · link live" : ""}
                </div>
                <div className="mt-1 text-[14.5px] font-medium">{i.title}</div>
                <div className="mt-0.5 truncate text-[12px] text-subtle">{i.url}</div>
              </a>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

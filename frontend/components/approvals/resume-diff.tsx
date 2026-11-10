"use client";

import { FileDown, ShieldAlert, ShieldCheck } from "lucide-react";

import { AgentAvatar } from "@/components/agents/agent-avatar";
import { Badge } from "@/components/ui/badge";
import { buttonClass } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/misc";
import { useDecideBullet } from "@/lib/queries";
import type { MatchDetail, TailoredBullet } from "@/lib/types";
import { cn } from "@/lib/utils";

type Piece = { text: string; kind: "same" | "add" | "del" };

/** Word-level diff (LCS). Bullets are short, so the quadratic table is fine. */
export function wordDiff(before: string, after: string): { before: Piece[]; after: Piece[] } {
  const a = before.split(/(\s+)/);
  const b = after.split(/(\s+)/);
  const t = Array.from({ length: a.length + 1 }, () => new Array<number>(b.length + 1).fill(0));
  for (let i = a.length - 1; i >= 0; i--) for (let j = b.length - 1; j >= 0; j--) t[i][j] = a[i] === b[j] ? t[i + 1][j + 1] + 1 : Math.max(t[i + 1][j], t[i][j + 1]);
  const outA: Piece[] = [];
  const outB: Piece[] = [];
  let i = 0;
  let j = 0;
  while (i < a.length && j < b.length) {
    if (a[i] === b[j]) {
      outA.push({ text: a[i], kind: "same" });
      outB.push({ text: b[j], kind: "same" });
      i++;
      j++;
    } else if (t[i + 1][j] >= t[i][j + 1]) outA.push({ text: a[i++], kind: "del" });
    else outB.push({ text: b[j++], kind: "add" });
  }
  while (i < a.length) outA.push({ text: a[i++], kind: "del" });
  while (j < b.length) outB.push({ text: b[j++], kind: "add" });
  return { before: outA, after: outB };
}

function Pieces({ pieces }: { pieces: Piece[] }) {
  return (
    <>
      {pieces.map((p, i) =>
        p.kind === "same" || !p.text.trim() ? (
          <span key={i}>{p.text}</span>
        ) : p.kind === "add" ? (
          <ins key={i} className="rounded-[3px] bg-cobalt-subtle px-0.5 text-text no-underline">
            {p.text}
          </ins>
        ) : (
          <del key={i} className="text-text-3 decoration-[color-mix(in_oklab,var(--error)_60%,transparent)]">
            {p.text}
          </del>
        ),
      )}
    </>
  );
}

function BulletRow({ b, matchId, editable }: { b: TailoredBullet; matchId: string; editable: boolean }) {
  const decide = useDecideBullet(matchId);
  const changed = b.rewritten.trim() !== b.original.trim();
  const diff = changed ? wordDiff(b.original, b.rewritten) : null;
  const usingRewrite = changed && !b.reverted && !b.declined;
  return (
    <li className="space-y-2.5 py-4 first:pt-0 last:pb-0">
      {diff && !b.reverted ? (
        <div className="space-y-2 text-[13.5px] leading-relaxed">
          <p className={cn("transition-opacity duration-[var(--dur-fast)]", usingRewrite ? "text-text" : "text-text-3 opacity-70")}>
            <span className="eyebrow mr-2 align-[1px]">After</span>
            <Pieces pieces={diff.after} />
          </p>
          <p className={cn("transition-opacity duration-[var(--dur-fast)]", usingRewrite ? "text-text-3" : "text-text")}>
            <span className="eyebrow mr-2 align-[1px]">Before</span>
            <Pieces pieces={usingRewrite ? diff.before : diff.before.map((p) => ({ ...p, kind: "same" as const }))} />
          </p>
        </div>
      ) : (
        <p className="text-[13.5px] leading-relaxed text-text">{b.original}</p>
      )}
      <div className="flex flex-wrap items-center gap-2">
        {b.reverted ? (
          <Badge tone="warning">
            <ShieldAlert /> Guard kept your original wording
          </Badge>
        ) : !changed ? (
          <Badge tone="outline">Original wording, moved up</Badge>
        ) : (
          <div role="radiogroup" aria-label="Which wording goes on the resume" className="inline-flex rounded-[var(--radius-control)] border border-border bg-elevated p-0.5">
            {[
              { v: false, label: "Use rewrite" },
              { v: true, label: "Keep original" },
            ].map((o) => (
              <button
                key={o.label}
                type="button"
                role="radio"
                aria-checked={!!b.declined === o.v}
                disabled={!editable || decide.isPending}
                onClick={() => !!b.declined !== o.v && decide.mutate({ sourceId: b.source_id, declined: o.v })}
                className={cn(
                  "h-9 rounded-[6px] px-3 text-[12.5px] font-medium transition-colors duration-[var(--dur-fast)] disabled:cursor-not-allowed md:h-7",
                  !!b.declined === o.v ? "bg-surface text-text shadow-[var(--highlight)] ring-1 ring-border" : "text-text-2 hover:text-text",
                )}
              >
                {o.label}
              </button>
            ))}
          </div>
        )}
        {b.keywords.slice(0, 4).map((k) => (
          <span key={k} className="rounded-[5px] border border-border px-1.5 py-0.5 text-[11.5px] text-text-3">
            {k}
          </span>
        ))}
      </div>
    </li>
  );
}

/** Tailor's rewrites against your base resume: accept or keep your original wording per bullet. */
export function ResumeDiff({ match, matchId, editable }: { match?: MatchDetail; matchId: string; editable: boolean }) {
  if (!match) return <Skeleton agent="tailor" className="min-h-64" />;
  const t = match.tailored;
  const accepted = t ? t.bullets.filter((b) => !b.reverted && !b.declined && b.rewritten.trim() !== b.original.trim()).length : 0;
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <AgentAvatar agent="tailor" size={32} decorative />
          <div>
            <div className="text-[14px] font-semibold">Tailor</div>
            <p className="text-[13px] text-text-2">
              {t ? (
                <>
                  I rewrote bullets for this role using only what’s on your resume. <span className="num">{accepted}</span> rewrite{accepted === 1 ? "" : "s"} in use.
                </>
              ) : (
                "No tailored resume for this job yet."
              )}
            </p>
          </div>
        </div>
        <a href={`/api/matches/${matchId}/resume?format=pdf`} download className={buttonClass({ variant: "secondary", size: "sm", className: "h-11 md:h-8" })}>
          <FileDown /> Resume PDF
        </a>
      </div>
      {t && (
        <>
          <div className="flex items-center gap-2 rounded-[var(--radius-control)] border border-border bg-elevated px-3 py-2 text-[12.5px] text-text-2">
            {t.guard_report.passed ? <ShieldCheck className="size-4 shrink-0 text-done" /> : <ShieldAlert className="size-4 shrink-0 text-your-turn" />}
            {t.guard_report.passed
              ? `Every rewrite passed the no-fabrication check (${t.guard_report.checked} checked).`
              : `${t.guard_report.violations.length} rewrite${t.guard_report.violations.length === 1 ? "" : "s"} mentioned something not on your resume, so the guard kept your wording.`}
          </div>
          <ul className="divide-y divide-border">
            {t.bullets.map((b) => (
              <BulletRow key={b.source_id} b={b} matchId={matchId} editable={editable} />
            ))}
          </ul>
          <p className="num text-[12px] text-text-3">{t.model === "offline" ? "Offline: most relevant bullets, original wording" : `Written by ${t.model}`}</p>
        </>
      )}
    </div>
  );
}

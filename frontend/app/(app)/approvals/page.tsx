"use client";

import { ArrowRight, Inbox } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import { Reviewer, type ApproveWith, type DraftEdits } from "@/components/approvals/reviewer";
import { Badge } from "@/components/ui/badge";
import { buttonClass } from "@/components/ui/button";
import { Card, Panel } from "@/components/ui/card";
import { EmptyState, Kbd, PageHeader, Segmented, Skeleton } from "@/components/ui/misc";
import { ScoreRing } from "@/components/ui/score-ring";
import { Sheet, SheetContent } from "@/components/ui/sheet";
import { gmailUrl, mailtoUrl, reserveTab, sendTo } from "@/lib/compose";
import { useConfig, useDecideDraft, useDrafts, useSendApplication, useUsage } from "@/lib/queries";
import type { DraftWithJob } from "@/lib/types";
import { useMediaQuery } from "@/lib/use-media";
import { ago, cn } from "@/lib/utils";

type View = "pending" | "approved" | "sent" | "rejected";

function QueueItem({ d, active, onSelect }: { d: DraftWithJob; active: boolean; onSelect: () => void }) {
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-current={active || undefined}
      className={cn(
        "relative flex w-full items-center gap-3 rounded-[var(--radius-control)] px-3 py-3 text-left transition-colors duration-[var(--dur-fast)]",
        active ? "bg-elevated" : "hover:bg-elevated/60",
      )}
    >
      {active && <span aria-hidden className="absolute inset-y-2.5 left-0 w-[2px] rounded-full bg-cobalt" />}
      <ScoreRing score={d.score} size={40} stroke={3.5} />
      <span className="min-w-0 flex-1">
        <span className="flex items-baseline justify-between gap-2">
          <span className="truncate text-[14px] font-medium">{d.company}</span>
          <span className="shrink-0 text-[11.5px] text-text-3">{ago(d.created_at)}</span>
        </span>
        <span className="mt-0.5 block truncate text-[13px] text-text-2">{d.title}</span>
        <span className="mt-1.5 flex gap-1.5">
          {d.kind === "referral" ? <Badge tone="accent">Referral</Badge> : d.to_email ? <Badge tone="success">Has recipient</Badge> : <Badge tone="warning">Needs recipient</Badge>}
        </span>
      </span>
    </button>
  );
}

export default function ApprovalsPage() {
  const [view, setView] = useState<View>("pending");
  const { data, isLoading } = useDrafts(view);
  const decide = useDecideDraft();
  const sendApp = useSendApplication();
  const { data: config } = useConfig();
  const { data: usage } = useUsage();
  const desktop = useMediaQuery("(min-width: 1024px)");
  const [selected, setSelected] = useState<string | null>(null);
  const [sheet, setSheet] = useState(false);

  // ⌘K "Review next approval" links here with ?draft=<id>.
  useEffect(() => {
    const id = new URLSearchParams(window.location.search).get("draft");
    if (id) {
      setSelected(id);
      setSheet(true);
    }
  }, []);

  const drafts = useMemo(() => data ?? [], [data]);
  const current = drafts.find((d) => d.id === selected) ?? drafts[0];
  const index = current ? drafts.findIndex((d) => d.id === current.id) : -1;

  const move = useCallback(
    (delta: number) => {
      if (index < 0) return;
      setSelected(drafts[Math.max(0, Math.min(drafts.length - 1, index + delta))].id);
    },
    [drafts, index],
  );

  // When a decision lands, go to the neighbour; on phones close the reviewer after the last one.
  const advance = useCallback(() => {
    const next = drafts[index + 1] ?? drafts[index - 1];
    setSelected(next?.id ?? null);
    if (!next) setSheet(false);
  }, [drafts, index]);

  const approve = (how: ApproveWith, edits: DraftEdits) => {
    if (!current) return;
    if (how === "send") {
      sendApp.mutate({ id: current.id, ...edits }, { onSuccess: advance });
      return;
    }
    // Reserve the Gmail tab inside the click or key press, or the popup blocker eats it after the await.
    const tab = how === "gmail" ? reserveTab() : null;
    decide.mutate(
      { id: current.id, decision: "approve", ...edits },
      {
        onSuccess: (d) => {
          advance();
          const mail = { to: d.to_email, cc: d.cc_email, subject: d.subject, body: d.email_body };
          sendTo(tab, how === "gmail" ? gmailUrl(mail) : mailtoUrl(mail));
        },
        onError: () => tab?.close(),
      },
    );
  };

  const reject = () => current && decide.mutate({ id: current.id, decision: "reject" }, { onSuccess: advance });

  const reviewer = (onClose?: () => void) =>
    current && (
      <Reviewer
        key={view}
        draft={current}
        index={index}
        total={drafts.length}
        onMove={move}
        onApprove={approve}
        onReject={reject}
        busy={decide.isPending || sendApp.isPending}
        smtp={!!config?.smtp_enabled}
        onClose={onClose}
      />
    );

  return (
    <div>
      <PageHeader
        title="Approvals"
        description="The crew pauses here. Nothing is sent until you approve it."
        action={
          <div className="flex flex-wrap items-center gap-3">
            {usage && (
              <span className="num text-[12.5px] text-text-3">
                {usage.week_applications} of {usage.weekly_cap} this week
              </span>
            )}
            <Segmented
              value={view}
              onChange={(v) => {
                setView(v);
                setSelected(null);
              }}
              options={[
                { value: "pending", label: "Pending" },
                { value: "approved", label: "Approved" },
                { value: "sent", label: "Sent" },
                { value: "rejected", label: "Rejected" },
              ]}
            />
          </div>
        }
      />

      {isLoading ? (
        <Skeleton agent="outreach" className="h-[min(640px,70dvh)]" />
      ) : !drafts.length ? (
        <Card>
          {view === "pending" ? (
            <EmptyState
              agent="outreach"
              action={
                <Link href="/jobs" className={buttonClass({ variant: "secondary" })}>
                  See your matches <ArrowRight />
                </Link>
              }
            />
          ) : (
            <EmptyState icon={<Inbox />} title={`No ${view} drafts`} description={view === "sent" ? "Applications you send appear here." : undefined} />
          )}
        </Card>
      ) : (
        <Panel className="overflow-hidden lg:grid lg:h-[calc(100dvh-210px)] lg:min-h-[600px] lg:grid-cols-[minmax(300px,360px)_minmax(0,1fr)]">
          <div className="flex min-h-0 flex-col lg:border-r lg:border-border">
            <div className="flex items-center justify-between px-4 pt-3 pb-2">
              <span className="eyebrow">
                Queue · <span className="num">{drafts.length}</span>
              </span>
              <span className="hidden items-center gap-1 text-[11.5px] text-text-3 xl:flex">
                <Kbd>J</Kbd>
                <Kbd>K</Kbd> to move
              </span>
            </div>
            <ul className="min-h-0 flex-1 space-y-0.5 overflow-y-auto overscroll-contain px-2 pb-2">
              {drafts.map((d) => (
                <li key={d.id}>
                  <QueueItem
                    d={d}
                    active={desktop && current?.id === d.id}
                    onSelect={() => {
                      setSelected(d.id);
                      if (!desktop) setSheet(true);
                    }}
                  />
                </li>
              ))}
            </ul>
          </div>
          {/* ≥1024: the reviewer sits beside the queue. Smaller screens open it full-screen. */}
          <div className="hidden min-h-0 lg:block">{desktop && reviewer()}</div>
        </Panel>
      )}

      {!desktop && (
        <Sheet open={sheet && !!current} onOpenChange={setSheet}>
          <SheetContent title={current ? `${current.company} · ${current.title}` : "Draft"} full hideHeader className="md:w-[min(640px,100vw)]">
            {reviewer(() => setSheet(false))}
          </SheetContent>
        </Sheet>
      )}
    </div>
  );
}

"use client";

import { DndContext, DragOverlay, KeyboardSensor, PointerSensor, useDraggable, useDroppable, useSensor, useSensors, type DragEndEvent } from "@dnd-kit/core";
import { ArrowRightLeft, BellRing, GripVertical, KanbanSquare, Table2, Eye } from "lucide-react";
import { motion, useReducedMotion } from "motion/react";
import Link from "next/link";
import { useMemo, useState } from "react";

import { AgentAvatar } from "@/components/agents/agent-avatar";
import { Card } from "@/components/ui/card";
import { EmptyState, PageHeader, Segmented, Skeleton } from "@/components/ui/misc";
import { Popover, PopoverClose, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { ScoreRing } from "@/components/ui/score-ring";
import { useMatches, useSetOutcome, useUpdateMatch } from "@/lib/queries";
import type { Match, Stage } from "@/lib/types";
import { useMediaQuery } from "@/lib/use-media";
import { ago, cn } from "@/lib/utils";

type ColKey = "shortlisted" | "draft" | "approved" | "sent" | "replied" | "interview" | "offer" | "closed";

interface Col {
  key: ColKey;
  label: string;
  hint: string;
  has: (m: Match) => boolean;
  /** Where a card dropped here goes. Columns without one are filled by the crew, not by dragging. */
  move?: { stage: Stage; replied?: boolean };
}

const replied = (m: Match) => m.outcome === "replied";

/** The board reads stages, drafts and outcomes; it never invents a state the data doesn't have. */
const COLUMNS: Col[] = [
  { key: "shortlisted", label: "Shortlisted", hint: "Above your fit threshold", has: (m) => m.stage === "shortlisted" && !m.pending_draft, move: { stage: "shortlisted" } },
  { key: "draft", label: "Draft ready", hint: "Waiting in Approvals", has: (m) => (m.stage === "shortlisted" || m.stage === "found") && m.pending_draft },
  { key: "approved", label: "Approved", hint: "Send it from your mail app", has: (m) => m.stage === "applied" && m.approved_draft && !m.sent_draft && !replied(m) },
  { key: "sent", label: "Sent", hint: "Follow up after 7 days", has: (m) => m.stage === "applied" && (m.sent_draft || !m.approved_draft) && !replied(m), move: { stage: "applied" } },
  { key: "replied", label: "Replied", hint: "They wrote back", has: (m) => m.stage === "applied" && replied(m), move: { stage: "applied", replied: true } },
  { key: "interview", label: "Interview", hint: "In conversation", has: (m) => m.stage === "interview", move: { stage: "interview" } },
  { key: "offer", label: "Offer", hint: "Congratulations", has: (m) => m.stage === "offer", move: { stage: "offer" } },
  { key: "closed", label: "Closed", hint: "Rejected or withdrawn", has: (m) => m.stage === "rejected", move: { stage: "rejected" } },
];

const colOf = (m: Match) => COLUMNS.find((c) => c.has(m))?.key;

function useMove() {
  const update = useUpdateMatch();
  const outcome = useSetOutcome();
  return (m: Match, to: Col) => {
    if (!to.move || colOf(m) === to.key) return;
    if (to.move.replied) {
      if (m.stage !== "applied") update.mutate({ id: m.id, stage: "applied" });
      outcome.mutate({ id: m.id, outcome: "replied" });
    } else update.mutate({ id: m.id, stage: to.move.stage });
  };
}

/** A non-drag way to move a card: works with a keyboard, a screen reader and on phones. */
function MoveMenu({ m }: { m: Match }) {
  const move = useMove();
  const here = colOf(m);
  return (
    <Popover>
      <PopoverTrigger asChild>
        <button type="button" onPointerDown={(e) => e.stopPropagation()} aria-label={`Move ${m.job.title}`} className="grid size-9 shrink-0 place-items-center rounded-[var(--radius-control)] text-text-3 hover:bg-elevated hover:text-text md:size-7">
          <ArrowRightLeft className="size-3.5" />
        </button>
      </PopoverTrigger>
      <PopoverContent label="Move to" className="w-56 p-1.5">
        <div className="eyebrow px-2.5 pt-1.5 pb-1">Move to</div>
        {COLUMNS.filter((c) => c.move).map((c) => (
          <PopoverClose asChild key={c.key}>
            <button
              type="button"
              disabled={c.key === here}
              onClick={() => move(m, c)}
              className="flex min-h-11 w-full items-center rounded-[var(--radius-control)] px-2.5 text-left text-[13.5px] hover:bg-elevated disabled:text-text-3 disabled:hover:bg-transparent md:min-h-9"
            >
              {c.label}
              {c.key === here && <span className="ml-auto text-[12px]">Here</span>}
            </button>
          </PopoverClose>
        ))}
      </PopoverContent>
    </Popover>
  );
}

function CardBody({ m, dragging }: { m: Match; dragging?: boolean }) {
  const due = m.follow_up_at && new Date(m.follow_up_at) <= new Date() && m.stage === "applied";
  return (
    <div className={cn("card p-3 transition-shadow duration-[var(--dur-fast)]", dragging && "rotate-[1.5deg] shadow-[var(--shadow-2)] ring-1 ring-[var(--cobalt)]")}>
      <div className="flex items-start gap-2.5">
        <ScoreRing score={m.score} size={34} stroke={3} />
        <div className="min-w-0 flex-1">
          <Link href={`/jobs/${m.id}`} className="line-clamp-2 text-[13.5px] leading-snug font-semibold hover:text-cobalt-text" onPointerDown={(e) => e.stopPropagation()} title={m.job.title}>
            {m.job.title}
          </Link>
          <div className="mt-0.5 truncate text-[12.5px] text-text-2">{m.job.company}</div>
        </div>
        <MoveMenu m={m} />
      </div>
      <div className="mt-2.5 flex items-center justify-between gap-2 text-[12px] text-text-3">
        <span className="flex min-w-0 items-center gap-1.5">
          {m.sent_draft && <AgentAvatar agent="dispatch" size={20} decorative />}
          <span className="truncate">{m.applied_at ? `${m.sent_draft ? "Sent" : "Applied"} ${ago(m.applied_at)}` : `Found ${ago(m.created_at)}`}</span>
        </span>
        {!!m.proof_views && (
          <span className="inline-flex shrink-0 items-center gap-1 text-done" title={m.proof_last_viewed_at ? `Last opened ${ago(m.proof_last_viewed_at)}` : undefined}>
            <Eye className="size-3" /> Opened {m.proof_views}×
          </span>
        )}
        {due && (
          <span className="inline-flex shrink-0 items-center gap-1 font-medium text-your-turn">
            <BellRing className="size-3" /> Follow up
          </span>
        )}
        <GripVertical className="hidden size-3.5 shrink-0 text-text-3 md:block" aria-hidden />
      </div>
    </div>
  );
}

function DraggableCard({ m }: { m: Match }) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({ id: m.id, data: m });
  const reduce = useReducedMotion();
  return (
    <motion.div layout={!reduce} transition={{ type: "spring", stiffness: 520, damping: 38 }}>
      <div ref={setNodeRef} {...attributes} {...listeners} aria-roledescription="Draggable job card" className={cn("cursor-grab touch-none rounded-[var(--radius-card)] active:cursor-grabbing", isDragging && "opacity-30")}>
        <CardBody m={m} />
      </div>
    </motion.div>
  );
}

function Column({ col, items, wide = false }: { col: Col; items: Match[]; wide?: boolean }) {
  const { setNodeRef, isOver } = useDroppable({ id: col.key, disabled: !col.move });
  return (
    <section
      ref={setNodeRef}
      aria-label={`${col.label}, ${items.length}`}
      className={cn(
        "flex shrink-0 flex-col rounded-[var(--radius-panel)] border bg-surface transition-colors duration-[var(--dur-fast)]",
        wide ? "w-full" : "w-72",
        isOver ? "border-[var(--cobalt)] bg-cobalt-subtle" : "border-border",
      )}
    >
      <div className="flex items-center justify-between gap-2 px-3.5 pt-3 pb-2">
        <h2 className="flex items-center gap-2 text-[13.5px] font-semibold">
          {col.label}
          <span className="num rounded-full bg-elevated-2 px-1.5 text-[11px] text-text-2">{items.length}</span>
        </h2>
        <span className="truncate text-[12px] text-text-3">{col.hint}</span>
      </div>
      <div className="flex min-h-40 flex-1 flex-col gap-2 p-2">
        {items.map((m) => (
          <DraggableCard key={m.id} m={m} />
        ))}
        {!items.length && (
          <div className="grid flex-1 place-items-center rounded-[var(--radius-card)] border border-dashed border-border px-3 text-center text-[12.5px] text-text-3">
            {col.move ? "Drop a card here" : col.key === "draft" ? "Outreach puts drafts here" : "Approve a draft to see it here"}
          </div>
        )}
      </div>
    </section>
  );
}

function TableView({ items }: { items: Match[] }) {
  return (
    <Card className="overflow-x-auto">
      <table className="w-full min-w-[720px] text-left text-[13.5px]">
        <thead className="text-[12px] text-text-3">
          <tr className="border-b border-border">
            <th className="px-4 py-3 font-medium">Role</th>
            <th className="px-4 py-3 font-medium">Status</th>
            <th className="px-4 py-3 text-right font-medium">Fit</th>
            <th className="px-4 py-3 font-medium">Applied</th>
            <th className="px-4 py-3 font-medium">Follow up</th>
            <th className="px-4 py-3 font-medium">
              <span className="sr-only">Move</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {items.map((m) => {
            const col = COLUMNS.find((c) => c.has(m));
            return (
              <tr key={m.id} className="border-b border-border last:border-0 hover:bg-elevated/50">
                <td className="max-w-[320px] px-4 py-2.5">
                  <Link href={`/jobs/${m.id}`} className="block truncate font-medium hover:text-cobalt-text" title={m.job.title}>
                    {m.job.title}
                  </Link>
                  <div className="truncate text-[12.5px] text-text-2">{m.job.company}</div>
                </td>
                <td className="px-4 py-2.5 text-text-2">{col?.label}</td>
                <td className="num px-4 py-2.5 text-right">{Math.round(m.score)}</td>
                <td className="px-4 py-2.5 text-text-2">{m.applied_at ? ago(m.applied_at) : "—"}</td>
                <td className="px-4 py-2.5 text-text-2">{m.follow_up_at && m.stage === "applied" ? ago(m.follow_up_at) : "—"}</td>
                <td className="px-2 py-2.5">
                  <MoveMenu m={m} />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </Card>
  );
}

export default function TrackerPage() {
  const { data, isLoading } = useMatches({ stage: ["found", "shortlisted", "applied", "interview", "offer", "rejected"], limit: 500, sort: "score" });
  const move = useMove();
  const [active, setActive] = useState<Match | null>(null);
  const [view, setView] = useState<"board" | "table">("board");
  const [phoneCol, setPhoneCol] = useState<ColKey>("shortlisted");
  // One layout mounted at a time, so each card and column registers with drag-and-drop once.
  const wide = useMediaQuery("(min-width: 768px)");
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 6 } }), useSensor(KeyboardSensor));
  // "Found" jobs only belong on the board once Outreach has drafted for them.
  const items = useMemo(() => (data?.items ?? []).filter((m) => m.stage !== "found" || m.pending_draft), [data]);
  const byCol = useMemo(() => Object.fromEntries(COLUMNS.map((c) => [c.key, items.filter(c.has)])) as Record<ColKey, Match[]>, [items]);

  const onDragEnd = (e: DragEndEvent) => {
    setActive(null);
    const to = COLUMNS.find((c) => c.key === e.over?.id);
    const m = e.active.data.current as Match | undefined;
    if (to && m) move(m, to);
  };

  return (
    <div>
      <PageHeader
        title="Tracker"
        description="Drag cards between stages, or use the move button. Moving a job to Sent sets a follow-up reminder for 7 days later."
        action={
          <Segmented
            value={view}
            onChange={setView}
            options={[
              { value: "board", label: <span className="inline-flex items-center gap-1.5"><KanbanSquare className="size-4" />Board</span> },
              { value: "table", label: <span className="inline-flex items-center gap-1.5"><Table2 className="size-4" />Table</span> },
            ]}
          />
        }
      />
      {isLoading ? (
        <Skeleton agent="tracker" className="min-h-96" />
      ) : !items.length ? (
        <Card>
          <EmptyState agent="tracker" />
        </Card>
      ) : view === "table" ? (
        <TableView items={items} />
      ) : (
        <DndContext sensors={sensors} onDragStart={(e) => setActive(e.active.data.current as Match)} onDragEnd={onDragEnd} onDragCancel={() => setActive(null)}>
          {!wide ? (
            /* Phones: one column at a time, chosen with a scrollable switcher. */
            <div>
              <div role="tablist" aria-label="Columns" className="-mx-4 mb-3 flex gap-1.5 overflow-x-auto px-4 pb-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
                {COLUMNS.map((c) => (
                  <button
                    key={c.key}
                    type="button"
                    role="tab"
                    aria-selected={phoneCol === c.key}
                    onClick={() => setPhoneCol(c.key)}
                    className={cn(
                      "inline-flex min-h-11 shrink-0 items-center gap-1.5 rounded-full border px-3.5 text-[13px] font-medium",
                      phoneCol === c.key ? "border-transparent bg-cobalt text-on-cobalt" : "border-border text-text-2",
                    )}
                  >
                    {c.label}
                    <span className="num text-[11.5px] opacity-80">{byCol[c.key].length}</span>
                  </button>
                ))}
              </div>
              <Column col={COLUMNS.find((c) => c.key === phoneCol)!} items={byCol[phoneCol]} wide />
            </div>
          ) : (
            <div className="-mx-6 flex gap-3 overflow-x-auto px-6 pb-4 lg:-mx-8 lg:px-8">
              {COLUMNS.map((c) => (
                <Column key={c.key} col={c} items={byCol[c.key]} />
              ))}
            </div>
          )}
          <DragOverlay dropAnimation={{ duration: 220, easing: "cubic-bezier(0.22, 1, 0.36, 1)" }}>{active && <CardBody m={active} dragging />}</DragOverlay>
        </DndContext>
      )}
    </div>
  );
}

"use client";

import { Bell, BellRing } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { AgentAvatar } from "@/components/agents/agent-avatar";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import type { AgentKey } from "@/config/agents";
import { useMarkRead, useNotifications, useOverview } from "@/lib/queries";
import type { AppNotification } from "@/lib/types";
import { ago, cn } from "@/lib/utils";

/** Each alert is said by the agent that produced it. */
const SPEAKER: Record<string, AgentKey> = { new_match: "matcher", research: "researcher", skills: "interviewer" };

function href(n: AppNotification) {
  if (n.kind === "new_match" && n.match_id) return `/jobs/${n.match_id}`;
  if (n.kind === "skills") return "/skills";
  if (n.kind === "research") return "/settings#research";
  return "/dashboard";
}

/** Desktop notifications for alerts that arrive while the app is open (opt-in, per browser). */
function useDesktopAlerts(items: AppNotification[] | undefined) {
  const seen = useRef<Set<string> | null>(null);
  useEffect(() => {
    if (!items) return;
    if (seen.current === null) {
      seen.current = new Set(items.map((n) => n.id)); // don't replay history on page load
      return;
    }
    const fresh = items.filter((n) => !n.read_at && !seen.current!.has(n.id));
    fresh.forEach((n) => seen.current!.add(n.id));
    if (typeof Notification === "undefined" || Notification.permission !== "granted") return;
    for (const n of fresh.slice(0, 3)) {
      const note = new Notification(n.title, { body: n.body, tag: n.id, icon: "/icon.svg" });
      note.onclick = () => {
        window.focus();
        window.location.href = href(n);
      };
    }
  }, [items]);
}

export function NotificationBell() {
  const { data: items } = useNotifications();
  const { data: overview } = useOverview();
  const markRead = useMarkRead();
  const [open, setOpen] = useState(false);
  const [permission, setPermission] = useState<NotificationPermission | "unsupported">("default");
  useDesktopAlerts(items);

  useEffect(() => setPermission(typeof Notification === "undefined" ? "unsupported" : Notification.permission), []);

  const unread = overview?.unread_notifications ?? items?.filter((n) => !n.read_at).length ?? 0;

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-label={`Notifications${unread ? `, ${unread} unread` : ""}`}
          className="relative grid size-11 shrink-0 place-items-center rounded-[var(--radius-control)] text-text-2 transition-colors hover:bg-elevated hover:text-text md:size-9 md:border md:border-border md:bg-surface md:hover:border-border-strong"
        >
          {unread ? <BellRing className="size-[18px] text-cobalt-text md:size-4" /> : <Bell className="size-[18px] md:size-4" />}
          {!!unread && (
            <span aria-hidden className="num absolute top-1.5 right-1.5 grid h-4 min-w-4 place-items-center rounded-full bg-cobalt px-1 text-[10px] font-semibold text-on-cobalt md:-top-1 md:-right-1">
              {unread > 9 ? "9+" : unread}
            </span>
          )}
        </button>
      </PopoverTrigger>

      <PopoverContent label="Notifications" className="w-[min(384px,calc(100vw-24px))]">
        <div className="flex items-center justify-between border-b border-border px-4 py-3">
          <div className="text-[14px] font-semibold">From your crew</div>
          {!!unread && (
            <button type="button" onClick={() => markRead.mutate(undefined)} className="rounded-[6px] px-1.5 py-0.5 text-[12.5px] font-medium text-cobalt-text hover:bg-cobalt-subtle">
              Mark all read
            </button>
          )}
        </div>
        {permission === "default" && (
          <button
            type="button"
            onClick={() => Notification.requestPermission().then(setPermission)}
            className="flex w-full items-center gap-2 border-b border-border bg-cobalt-subtle px-4 py-2.5 text-left text-[12.5px] text-cobalt-text"
          >
            <BellRing className="size-3.5 shrink-0" /> Get a desktop alert when a new job matches you
          </button>
        )}
        <ul className="max-h-[min(440px,60dvh)] overflow-y-auto overscroll-contain">
          {!items?.length ? (
            <li className="flex flex-col items-center gap-3 px-6 py-10 text-center">
              <AgentAvatar agent="scout" size={64} decorative />
              <div>
                <div className="text-[14px] font-medium">Nothing yet</div>
                <div className="mt-1 text-[13px] text-text-2">I’ll tell you here when I find something for you.</div>
              </div>
            </li>
          ) : (
            items.map((n) => (
              <li key={n.id}>
                <Link
                  href={href(n)}
                  onClick={() => {
                    setOpen(false);
                    if (!n.read_at) markRead.mutate([n.id]);
                  }}
                  className={cn("flex gap-3 border-b border-border px-4 py-3 transition-colors last:border-0 hover:bg-elevated", !n.read_at && "bg-cobalt-subtle/50")}
                >
                  <AgentAvatar agent={SPEAKER[n.kind] ?? "pilot"} size={32} decorative />
                  <div className="min-w-0 flex-1">
                    <div className="text-[13px] leading-snug font-medium text-text">{n.title}</div>
                    {n.body && <div className="mt-0.5 line-clamp-2 text-[12.5px] text-text-2">{n.body}</div>}
                    <div className="mt-1 text-[11.5px] text-text-3">{ago(n.created_at)}</div>
                  </div>
                  {!n.read_at && <span aria-label="Unread" className="mt-2 size-1.5 shrink-0 rounded-full bg-cobalt" />}
                </Link>
              </li>
            ))
          )}
        </ul>
      </PopoverContent>
    </Popover>
  );
}

"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useEffect, useSyncExternalStore } from "react";

import { agentToast } from "@/components/agents/agent-toast";

interface Fit { match_id: string; title: string; company: string; score: number }

// Match ids that arrived while this tab was open: rows for them get a highlight. Replaced (not mutated)
// on change so useSyncExternalStore sees a new snapshot.
let arrived: ReadonlySet<string> = new Set<string>();
let connected = false;
const listeners = new Set<() => void>();
const emit = () => listeners.forEach((l) => l());
const subscribe = (l: () => void) => (listeners.add(l), () => listeners.delete(l));

export const useLiveConnected = () => useSyncExternalStore(subscribe, () => connected, () => false);
export const useJustArrived = () => useSyncExternalStore(subscribe, () => arrived, () => arrived);

/** One Server-Sent Events stream per tab: new matches land on the dashboard the moment the Matcher
 *  commits them (before tailoring finishes), with a toast for each strong fit. Polling stays as a fallback. */
export function useLiveUpdates() {
  const qc = useQueryClient();
  const router = useRouter();

  useEffect(() => {
    const es = new EventSource("/api/events", { withCredentials: true });
    const refresh = (...keys: string[]) => keys.forEach((k) => qc.invalidateQueries({ queryKey: [k] }));

    es.onopen = () => {
      connected = true;
      emit();
      refresh("matches", "overview"); // catch up on anything that landed while disconnected
    };
    es.onerror = () => {
      connected = false;
      emit();
    };
    es.addEventListener("new_matches", (e) => {
      const data = JSON.parse((e as MessageEvent).data) as { count: number; fits: Fit[] };
      refresh("matches", "overview", "notifications");
      arrived = new Set([...arrived, ...data.fits.map((f) => f.match_id)]);
      emit();
      data.fits.slice(0, 3).forEach((f) =>
        agentToast("matcher", `${f.title} at ${f.company} is a ${f.score} fit`, {
          action: { label: "View", onClick: () => router.push(`/jobs/${f.match_id}`) },
          duration: 10_000,
        }),
      );
    });
    // A finished run can change the open job too (Prepare application: tailored resume, draft, ATS comparison).
    es.addEventListener("run_updated", () => refresh("overview", "runs", "drafts", "matches", "match", "ats-compare"));

    return () => {
      es.close();
      connected = false;
      emit();
    };
  }, [qc, router]);
}

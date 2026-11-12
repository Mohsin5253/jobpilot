"use client";

/**
 * Flowtype, inside the mock interview. Push-to-talk for spoken answers: hold Right Ctrl (Right Option/Alt on a Mac) or the Speak button and
 * talk; let go and the polished transcript is inserted at the cursor. Double-tap the key (or tap the button) for
 * hands-free. The mic stays open while the answer box is active, with a 500 ms pre-roll so the first word is never
 * clipped and a 250 ms post-roll after release. Silence is trimmed and a take with no speech sends nothing.
 * Raw words are never streamed to the screen: the whole take is transcribed, fixed and then inserted.
 * Two modes: Polished (fillers, false starts and self-corrections cleaned up, punctuation and lists, checked by the
 * server's guardrails) and Word for word (exactly what you said). After a polished take, `restoreExactWords()` swaps
 * the cleaned text for the words you actually said.
 * Logs latency (release → text) and, at submit, whether you edited the text (the Dictation Edit Rate).
 *
 * From the Flowtype desktop app:
 * - context: the answer around the cursor at key-down, the company, role and round go with each take, so names and
 *   terms already on screen are spelled right, and a take dictated mid-sentence continues it;
 * - speculative chunking: during a long answer, finished stretches are transcribed while you're still talking, so
 *   only the last few seconds are left at release;
 * - learning: at submit, a word you corrected after dictating ("Ishan" → "Ishaan") is learned for next time.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "@/lib/api";
import { serverStt, tidy } from "@/lib/dictation";
import { Capture, TARGET_RATE } from "@/lib/flow/capture";
import { editRatio } from "@/lib/flow/edit";
import { bindPushToTalk } from "@/lib/flow/hotkey";
import { trim } from "@/lib/flow/vad";
import { findCut } from "@/lib/flow/speculative";
import { encodeWav } from "@/lib/flow/wav";

type SttOut = {
  text: string;
  corrections?: { heard: string; fixed: string }[];
  dictation_id?: string;
  timings?: Record<string, number | boolean>;
  mode?: SpeechMode;
  cleaned?: boolean;
  raw?: string | null;
  continued?: boolean;
};
export type SpeechMode = "polished" | "verbatim";
/** Where the answer is going: the round and the job, plus the text around the cursor (read at key-down). */
export type FlowContext = { company?: string; role?: string; roundName?: string; kind?: string; around?: () => { before: string; after: string } };

const SPEC_EVERY_MS = 300;

export function useFlow({
  hint,
  active,
  onText,
  onReplace,
  context = {},
  onLearned,
}: {
  hint: string;
  active: boolean;
  onText: (text: string) => void;
  onReplace?: (from: string, to: string) => void;
  context?: FlowContext;
  onLearned?: (words: string[]) => void;
}) {
  const [supported, setSupported] = useState(false);
  const [listening, setListening] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const [handsFree, setHandsFree] = useState(false);
  const [level, setLevel] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [corrections, setCorrections] = useState<{ heard: string; fixed: string }[]>([]);
  const [source, setSource] = useState<"whisper" | null>(null);
  const [latencyMs, setLatencyMs] = useState<number | null>(null);
  const [mode, setModeState] = useState<SpeechMode>("polished");
  const [last, setLast] = useState<{ text: string; raw: string; cleaned: boolean } | null>(null);
  const cap = useRef<Capture | null>(null);
  const st = useRef({ listening: false, transcribing: false, handsFree: false });
  const takes = useRef<{ id: string; text: string }[]>([]);
  const cb = useRef({ hint, onText, onReplace, mode, context, onLearned });
  cb.current = { hint, onText, onReplace, mode, context, onLearned };
  // This take: the context read at key-down, and the speculative chunks sent so far.
  const take = useRef<{ fields: Record<string, string>; cut: number; chunks: Promise<string>[]; timer: number | null }>({ fields: {}, cut: 0, chunks: [], timer: null });

  useEffect(() => {
    let alive = true;
    serverStt().then((ok) => alive && setSupported(ok && typeof window !== "undefined" && "AudioContext" in window && !!navigator.mediaDevices?.getUserMedia));
    api.get<{ mode?: SpeechMode }>("/stt/words").then((r) => alive && r.mode && setModeState(r.mode), () => {});
    return () => {
      alive = false;
    };
  }, []);

  const setMode = useCallback((m: SpeechMode) => {
    setModeState(m);
    api.put("/stt/mode", { mode: m }).catch(() => {});
  }, []);

  // The mic is open while the answer box is active, so the pre-roll is always filling.
  useEffect(() => {
    if (!supported || !active) return;
    const c = new Capture();
    let raf = 0;
    c.onLevel = (v) => {
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() => setLevel(v));
    };
    c.openMic().then(
      () => (cap.current = c),
      () => setError("Microphone blocked. Allow it from the icon in the address bar, or type your answer."),
    );
    return () => {
      cancelAnimationFrame(raf);
      if (take.current.timer !== null) window.clearInterval(take.current.timer);
      take.current.timer = null;
      c.close();
      if (cap.current === c) cap.current = null;
    };
  }, [supported, active]);

  /** The form fields every request of this take carries: the question, the job, the round, the answer around the cursor. */
  const readFields = () => {
    const ctx = cb.current.context;
    const around = ctx.around?.() ?? { before: "", after: "" };
    return {
      hint: cb.current.hint.slice(0, 500),
      before: around.before.slice(-3000),
      after: around.after.slice(0, 1500),
      company: (ctx.company ?? "").slice(0, 120),
      role: (ctx.role ?? "").slice(0, 160),
      round_name: (ctx.roundName ?? "").slice(0, 80),
      kind: (ctx.kind ?? "").slice(0, 40),
    };
  };
  const form = (fields: Record<string, string>) => {
    const fd = new FormData();
    for (const [k, v] of Object.entries(fields)) if (v) fd.set(k, v);
    return fd;
  };

  /** Every 300 ms while talking: at a natural pause after 4+ s, send the finished stretch to be transcribed now. */
  const speculate = useCallback(() => {
    const c = cap.current;
    const t = take.current;
    if (!c || !st.current.listening) return;
    const window = c.since(t.cut);
    const k = findCut(window, TARGET_RATE);
    if (k === null) return;
    const chunk = trim(window.slice(0, k), TARGET_RATE);
    t.cut += Math.round((k * c.rate) / TARGET_RATE);
    if (!chunk.speech) {
      t.chunks.push(Promise.resolve(""));
      return;
    }
    const fd = form(t.fields);
    fd.set("audio", encodeWav(chunk.audio, TARGET_RATE), "chunk.wav");
    t.chunks.push(api.post<{ text: string }>("/stt/chunk", fd).then((r) => r.text || ""));
  }, []);

  const start = useCallback(() => {
    const c = cap.current;
    if (!c?.open || st.current.listening || st.current.transcribing) return;
    setError(null);
    c.begin();
    take.current = { fields: readFields(), cut: 0, chunks: [], timer: window.setInterval(speculate, SPEC_EVERY_MS) };
    st.current.listening = true;
    setListening(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [speculate]);

  const stop = useCallback(async () => {
    const c = cap.current;
    if (!c || !st.current.listening) return;
    st.current.listening = false;
    st.current.handsFree = false;
    setListening(false);
    setHandsFree(false);
    const releaseAt = performance.now();
    st.current.transcribing = true;
    setTranscribing(true);
    const t = take.current;
    if (t.timer !== null) window.clearInterval(t.timer);
    t.timer = null;
    try {
      const whole = await c.end();
      // The chunks sent while talking: if one failed, the whole take goes the normal way instead.
      const done = await Promise.allSettled(t.chunks);
      const ok = done.every((d) => d.status === "fulfilled");
      const prefix = ok ? done.map((d) => (d as PromiseFulfilledResult<string>).value).filter(Boolean).join(" ") : "";
      const v = trim(ok ? whole.slice(c.toTarget(t.cut)) : whole, TARGET_RATE);
      if (!v.speech && !prefix) return; // nothing said: nothing sent, nothing inserted
      const fd = form(t.fields);
      if (v.speech) fd.set("audio", encodeWav(v.audio, TARGET_RATE), "answer.wav");
      fd.set("audio_ms", String(Math.round((whole.length / TARGET_RATE) * 1000)));
      fd.set("mode", cb.current.mode);
      if (prefix) fd.set("prefix", prefix.slice(0, 20000));
      if (ok && t.chunks.length) fd.set("chunks", String(t.chunks.length));
      const r = await api.post<SttOut>("/stt", fd);
      // A polished take may be a numbered list, or start with "new paragraph": keep its line breaks. Text that
      // continues a sentence keeps its lower-case start.
      const text = r.text?.includes("\n") ? r.text.replace(/^[ \t]+|\s+$/g, "") : r.continued ? (r.text || "").replace(/\s+/g, " ").trim() : tidy(r.text || "");
      if (text) {
        cb.current.onText(text);
        setSource("whisper");
        const raw = tidy(r.raw || "");
        setLast({ text, raw, cleaned: !!r.cleaned && !!raw && raw !== text });
        setCorrections(r.corrections ?? []);
        const ms = Math.round(performance.now() - releaseAt);
        setLatencyMs(ms);
        if (r.dictation_id) {
          takes.current.push({ id: r.dictation_id, text });
          api.patch(`/stt/dictations/${r.dictation_id}`, { client_ms: ms }).catch(() => {});
        }
      }
    } catch (e) {
      setError((e as Error).message || "Transcription failed. Type your answer or try again.");
    } finally {
      st.current.transcribing = false;
      setTranscribing(false);
    }
  }, []);

  const startHandsFree = useCallback(() => {
    if (st.current.listening) return;
    start();
    st.current.handsFree = true;
    setHandsFree(true);
  }, [start]);

  // Right Ctrl: hold to talk, double-tap for hands-free.
  useEffect(() => {
    if (!supported || !active) return;
    return bindPushToTalk({
      onDown: start,
      onUp: () => void stop(),
      onDoubleTap: startHandsFree,
      isHandsFree: () => st.current.handsFree,
    });
  }, [supported, active, start, stop, startHandsFree]);

  /** The Speak button: a long press is push-to-talk; a tap toggles hands-free. */
  const press = useRef(0);
  const buttonHandlers = {
    onPointerDown: () => {
      press.current = performance.now();
      if (st.current.listening) return;
      start();
    },
    onPointerUp: () => {
      const held = performance.now() - press.current;
      if (st.current.handsFree) return void stop();
      if (held < 300) {
        st.current.handsFree = true;
        setHandsFree(true);
        return;
      }
      void stop();
    },
  };

  /** At submit: report for each take whether it was edited (the Edit Rate) and how much. When it was, the take and
   * the answer go along (compared in memory on the server, never stored), so a word you corrected is learned. */
  const reportEdits = useCallback((final: string) => {
    const learned: Promise<string[]>[] = [];
    for (const t of takes.current) {
      const ratio = editRatio(t.text, final);
      const edited = ratio > 0.02;
      learned.push(
        api
          .patch<{ learned?: string[] }>(`/stt/dictations/${t.id}`, { edited, edit_ratio: ratio, ...(edited ? { dictated: t.text, final: final.slice(0, 40000) } : {}) })
          .then((r) => r.learned ?? [], () => []),
      );
    }
    takes.current = [];
    Promise.all(learned).then((ls) => {
      const words = [...new Set(ls.flat())];
      if (words.length) cb.current.onLearned?.(words);
    });
  }, []);

  /** Undo the clean-up of the last take: put back exactly what you said. */
  const restoreExactWords = useCallback(() => {
    if (!last?.cleaned) return;
    cb.current.onReplace?.(last.text, last.raw);
    setLast({ ...last, text: last.raw, cleaned: false });
  }, [last]);

  return { supported, listening, transcribing, handsFree, level, error, corrections, source, latencyMs, start, stop, buttonHandlers, reportEdits, mode, setMode, cleaned: !!last?.cleaned, restoreExactWords };
}

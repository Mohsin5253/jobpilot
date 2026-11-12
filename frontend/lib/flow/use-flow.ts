"use client";

/**
 * Flow-style push-to-talk for spoken answers: hold Right Ctrl (Right Option/Alt on a Mac) or the Speak button and
 * talk; let go and the polished transcript is inserted at the cursor. Double-tap the key (or tap the button) for
 * hands-free. The mic stays open while the answer box is active, with a 500 ms pre-roll so the first word is never
 * clipped and a 250 ms post-roll after release. Silence is trimmed and a take with no speech sends nothing.
 * Raw words are never streamed to the screen: the whole take is transcribed, fixed and then inserted.
 * Two modes: Polished (fillers, false starts and self-corrections cleaned up, punctuation and lists, checked by the
 * server's guardrails) and Word for word (exactly what you said). After a polished take, `restoreExactWords()` swaps
 * the cleaned text for the words you actually said.
 * Logs latency (release → text) and, at submit, whether you edited the text (the Dictation Edit Rate).
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "@/lib/api";
import { serverStt, tidy } from "@/lib/dictation";
import { Capture, TARGET_RATE } from "@/lib/flow/capture";
import { editRatio } from "@/lib/flow/edit";
import { bindPushToTalk } from "@/lib/flow/hotkey";
import { trim } from "@/lib/flow/vad";
import { encodeWav } from "@/lib/flow/wav";

type SttOut = {
  text: string;
  corrections?: { heard: string; fixed: string }[];
  dictation_id?: string;
  timings?: Record<string, number | boolean>;
  mode?: SpeechMode;
  cleaned?: boolean;
  raw?: string | null;
};
export type SpeechMode = "polished" | "verbatim";

export function useFlow({ hint, active, onText, onReplace }: { hint: string; active: boolean; onText: (text: string) => void; onReplace?: (from: string, to: string) => void }) {
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
  const cb = useRef({ hint, onText, onReplace, mode });
  cb.current = { hint, onText, onReplace, mode };

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
      c.close();
      if (cap.current === c) cap.current = null;
    };
  }, [supported, active]);

  const start = useCallback(() => {
    const c = cap.current;
    if (!c?.open || st.current.listening || st.current.transcribing) return;
    setError(null);
    c.begin();
    st.current.listening = true;
    setListening(true);
  }, []);

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
    try {
      const take = await c.end();
      const v = trim(take, TARGET_RATE);
      if (!v.speech) return; // nothing said: nothing sent, nothing inserted
      const fd = new FormData();
      fd.set("audio", encodeWav(v.audio, TARGET_RATE), "answer.wav");
      fd.set("hint", cb.current.hint.slice(0, 500));
      fd.set("audio_ms", String(Math.round((v.audio.length / TARGET_RATE) * 1000)));
      fd.set("mode", cb.current.mode);
      const r = await api.post<SttOut>("/stt", fd);
      // A polished take may be a numbered list: keep its line breaks.
      const text = r.text?.includes("\n") ? r.text.trim() : tidy(r.text || "");
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

  /** At submit: report for each take whether it was edited (the Edit Rate) and how much. */
  const reportEdits = useCallback((final: string) => {
    for (const t of takes.current) {
      const ratio = editRatio(t.text, final);
      api.patch(`/stt/dictations/${t.id}`, { edited: ratio > 0.02, edit_ratio: ratio }).catch(() => {});
    }
    takes.current = [];
  }, []);

  /** Undo the clean-up of the last take: put back exactly what you said. */
  const restoreExactWords = useCallback(() => {
    if (!last?.cleaned) return;
    cb.current.onReplace?.(last.text, last.raw);
    setLast({ ...last, text: last.raw, cleaned: false });
  }, [last]);

  return { supported, listening, transcribing, handsFree, level, error, corrections, source, latencyMs, start, stop, buttonHandlers, reportEdits, mode, setMode, cleaned: !!last?.cleaned, restoreExactWords };
}

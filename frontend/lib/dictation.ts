"use client";

/**
 * Dictation for spoken interview answers, built for accuracy:
 * - Live: the browser's speech recognition (en-IN) shows words as you speak, and restarts itself after pauses
 *   (Chrome ends a session after a few seconds of silence) so long answers aren't cut off.
 * - Final: the same speech is recorded (64 kbps Opus, no noise suppression, which clips soft consonants) and, when you
 *   stop, transcribed by Whisper large-v3 on the server, which is much better with Indian English and technical terms.
 *   Its text replaces the live draft, unless it came back much shorter than what was heard live (a dropped stretch),
 *   in which case the live words are kept.
 * - Without the server model (or if it fails), the live transcript is kept, tidied (capitals, full stop, "I").
 * Audio is only sent for transcription; nothing is stored.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "@/lib/api";

type SRResult = { isFinal: boolean; 0: { transcript: string } };
type SR = {
  start: () => void;
  stop: () => void;
  abort: () => void;
  onresult: ((e: { resultIndex: number; results: ArrayLike<SRResult> }) => void) | null;
  onend: (() => void) | null;
  onerror: ((e: { error: string }) => void) | null;
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  maxAlternatives: number;
};

export type MicState = "unknown" | "granted" | "denied" | "unsupported";

/** Asks for the microphone now (the browser shows its permission prompt), then releases it. */
export async function requestMic(): Promise<MicState> {
  if (typeof navigator === "undefined" || !navigator.mediaDevices?.getUserMedia) return "unsupported";
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: AUDIO });
    stream.getTracks().forEach((t) => t.stop());
    return "granted";
  } catch {
    return "denied";
  }
}

// Echo cancellation stops the interviewer's voice leaking in; noise suppression is off because it clips soft
// consonants, and Whisper copes with background noise far better than with missing sounds.
const AUDIO: MediaTrackConstraints = { echoCancellation: true, noiseSuppression: false, autoGainControl: true, channelCount: 1 };

const words = (t: string) => t.split(/\s+/).filter(Boolean).length;

export type TranscriptSource = "whisper" | "browser";

export function tidy(text: string): string {
  let t = text.replace(/\s+/g, " ").trim();
  if (!t) return t;
  t = t.replace(/\bi\b/g, "I").replace(/(^|[.!?]\s+)([a-z])/g, (_, a, b) => a + b.toUpperCase());
  return /[.!?]$/.test(t) ? t : `${t}.`;
}

let sttEnabled: Promise<boolean> | null = null;
const serverStt = () => (sttEnabled ??= api.get<{ enabled: boolean }>("/stt/status").then((r) => r.enabled, () => false));

function pickMime(): string | undefined {
  if (typeof MediaRecorder === "undefined") return undefined;
  return ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus"].find((m) => MediaRecorder.isTypeSupported(m));
}

export function useDictation({ hint, onLive, onFinal }: { hint: string; onLive: (text: string) => void; onFinal: (text: string, source: TranscriptSource) => void }) {
  const [listening, setListening] = useState(false);
  const [source, setSource] = useState<TranscriptSource | null>(null);
  const [corrections, setCorrections] = useState<{ heard: string; fixed: string }[]>([]);
  const [transcribing, setTranscribing] = useState(false);
  const [level, setLevel] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const rec = useRef<SR | null>(null);
  const media = useRef<MediaRecorder | null>(null);
  const chunks = useRef<Blob[]>([]);
  const stream = useRef<MediaStream | null>(null);
  const active = useRef(false);
  const finals = useRef("");
  const raf = useRef(0);
  const cb = useRef({ onLive, onFinal, hint });
  cb.current = { onLive, onFinal, hint };

  const cleanup = useCallback(() => {
    cancelAnimationFrame(raf.current);
    stream.current?.getTracks().forEach((t) => t.stop());
    stream.current = null;
    setLevel(0);
  }, []);

  useEffect(
    () => () => {
      active.current = false;
      rec.current?.abort();
      if (media.current?.state === "recording") media.current.stop();
      cleanup();
    },
    [cleanup],
  );

  const start = useCallback(async () => {
    setError(null);
    setSource(null);
    setCorrections([]);
    if (!navigator.mediaDevices?.getUserMedia) {
      setError("This browser can't use the microphone. Type your answer instead.");
      return;
    }
    let s: MediaStream;
    try {
      s = await navigator.mediaDevices.getUserMedia({ audio: AUDIO });
    } catch {
      setError("Microphone blocked. Allow it from the icon in the address bar, or type your answer.");
      return;
    }
    stream.current = s;
    finals.current = "";
    active.current = true;
    setListening(true);

    // Level meter, so the student can see the mic is picking them up.
    try {
      const ctx = new AudioContext();
      const an = ctx.createAnalyser();
      an.fftSize = 512;
      ctx.createMediaStreamSource(s).connect(an);
      const buf = new Uint8Array(an.frequencyBinCount);
      const tick = () => {
        an.getByteTimeDomainData(buf);
        let peak = 0;
        for (const v of buf) peak = Math.max(peak, Math.abs(v - 128));
        setLevel(Math.min(1, peak / 60));
        if (active.current) raf.current = requestAnimationFrame(tick);
        else ctx.close().catch(() => {});
      };
      tick();
    } catch {
      /* no meter */
    }

    // Recording for the accurate (server) transcript.
    const mime = pickMime();
    if (mime) {
      chunks.current = [];
      const mr = new MediaRecorder(s, { mimeType: mime, audioBitsPerSecond: 64000 });
      mr.ondataavailable = (e) => e.data.size && chunks.current.push(e.data);
      mr.start(1000);
      media.current = mr;
    }

    // Live words from the browser, restarted after pauses until the student presses Stop.
    const W = window as unknown as { SpeechRecognition?: new () => SR; webkitSpeechRecognition?: new () => SR };
    const Ctor = W.SpeechRecognition ?? W.webkitSpeechRecognition;
    if (Ctor) {
      const make = () => {
        const r = new Ctor();
        r.lang = "en-IN";
        r.continuous = true;
        r.interimResults = true;
        r.maxAlternatives = 1;
        r.onresult = (e) => {
          let interim = "";
          for (let i = e.resultIndex; i < e.results.length; i++) {
            const res = e.results[i];
            if (res.isFinal) finals.current = `${finals.current} ${res[0].transcript}`.trim();
            else interim += res[0].transcript;
          }
          cb.current.onLive(`${finals.current} ${interim}`.trim());
        };
        r.onerror = (e) => {
          if (e.error === "not-allowed" || e.error === "service-not-allowed") setError("Live captions are blocked in this browser; your answer is still recorded and transcribed when you stop.");
        };
        r.onend = () => {
          if (active.current) {
            try {
              rec.current = make();
              rec.current.start();
            } catch {
              /* a restart race: the next result will start a new one */
            }
          }
        };
        return r;
      };
      rec.current = make();
      try {
        rec.current.start();
      } catch {
        /* already started */
      }
    }
  }, []);

  const stop = useCallback(async () => {
    if (!active.current) return;
    active.current = false;
    setListening(false);
    rec.current?.stop();
    const live = finals.current;
    const recorder = media.current;
    media.current = null;
    const blob = await new Promise<Blob | null>((resolve) => {
      if (!recorder || recorder.state !== "recording") return resolve(null);
      recorder.onstop = () => resolve(new Blob(chunks.current, { type: recorder.mimeType }));
      recorder.stop();
    });
    cleanup();
    if (blob && blob.size > 800 && (await serverStt())) {
      setTranscribing(true);
      try {
        const fd = new FormData();
        fd.set("audio", blob, `answer.${blob.type.includes("mp4") ? "m4a" : blob.type.includes("ogg") ? "ogg" : "webm"}`);
        fd.set("hint", cb.current.hint.slice(0, 500));
        const r = await api.post<{ text: string; corrections?: { heard: string; fixed: string }[] }>("/stt", fd);
        setCorrections(r.corrections ?? []);
        // Whisper occasionally skips a stretch after a long pause; if it heard far fewer words than the live captions
        // did, the live words are the safer record.
        const dropped = words(live) >= 12 && words(r.text) < 0.6 * words(live);
        if (r.text.trim() && !dropped) {
          setSource("whisper");
          cb.current.onFinal(tidy(r.text), "whisper");
          return;
        }
      } catch {
        /* fall back to the live transcript */
      } finally {
        setTranscribing(false);
      }
    }
    setSource(live.trim() ? "browser" : null);
    if (live.trim()) cb.current.onFinal(tidy(live), "browser");
    else cb.current.onFinal("", "browser");
  }, [cleanup]);

  return { listening, transcribing, level, error, source, corrections, start, stop };
}

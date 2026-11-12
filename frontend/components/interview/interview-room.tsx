"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ArrowRight, Check, Clock, Maximize, Mic, MicOff, RotateCcw, ShieldAlert, ShieldCheck, Volume2, VolumeX } from "lucide-react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState, type ClipboardEvent, type DragEvent, type KeyboardEvent } from "react";
import { toast } from "sonner";

import type { Problem } from "@/components/interview/coding-panel";
import { Interviewer3D, type InterviewerHandle } from "@/components/interview/interviewer-3d";
import { InterviewReport } from "@/components/interview/interview-report";
import { INTERVIEWERS, pickVoice, type InterviewerKey } from "@/components/interview/interviewers";
import { Badge } from "@/components/ui/badge";
import { Button, buttonClass } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { Textarea } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/misc";
import { ScoreRing } from "@/components/ui/score-ring";
import { api } from "@/lib/api";
import { requestMic, useDictation, type MicState } from "@/lib/dictation";
import { useFlow } from "@/lib/flow/use-flow";
import { cn } from "@/lib/utils";

type Q = { id: string; q: string; jd_line: string; skill: string | null; kind: string; round: number; round_name: string; seconds?: number; trend?: boolean; problem?: Problem };
type Score = {
  relevance: number;
  specificity: number;
  structure: number;
  score: number;
  tests: string;
  feedback: string[];
  integrity_flags?: string[];
  mode?: string;
  // coding review
  verdict?: string;
  summary?: string;
  tests_label?: string;
  time_complexity?: string;
  space_complexity?: string;
  optimal?: boolean;
  bugs?: string[];
  edge_cases_missed?: string[];
  code_quality?: string[];
  improvements?: string[];
  correctness?: number;
  efficiency?: number;
  quality?: number;
  communication?: number;
  clarification?: number;
  design?: number;
  testing?: number;
  follow_up?: string;
  ai?: boolean;
  language?: string;
};
type Round = { index: number; name: string; kind: string; intro: string; total: number; answered: number; score: number | null };
export type InterviewSession = {
  id: string;
  match_id: string;
  questions: Q[];
  answers: Record<string, string>;
  scores: Record<string, Score>;
  completed_at: string | null;
  status: "active" | "completed" | "terminated";
  meta: { industry?: string; industry_name?: string; interviewer?: InterviewerKey; strict?: boolean; job?: { title: string; company: string }; minutes?: number; level?: string; bar?: number };
  started_at?: string | null;
  rounds: Round[];
  integrity: { violations: number; max_violations: number; counts: Record<string, number>; flagged_answers: string[]; terminated_reason: string | null };
  report: { score: number | null; verdict: string; answered: number; total: number };
};

type IntegrityType = "tab_hidden" | "window_blur" | "fullscreen_exit" | "paste_blocked" | "copy_blocked" | "drop_blocked" | "shortcut_blocked" | "context_menu";

// The code editor (CodeMirror) loads only when a coding question starts.
const CodingPanel = dynamic(() => import("@/components/interview/coding-panel").then((m) => m.CodingPanel), { ssr: false, loading: () => <Skeleton className="min-h-[520px]" /> });

const fmt = (s: number) => `${Math.floor(s / 60)}:${String(Math.max(0, s) % 60).padStart(2, "0")}`;

export function InterviewRoom({ id }: { id: string }) {
  const qc = useQueryClient();
  const { data: s } = useQuery({ queryKey: ["interview", id], queryFn: () => api.get<InterviewSession>(`/interviews/${id}`) });
  if (!s) return <Skeleton className="min-h-[60vh]" />;
  return <Room s={s} setS={(x) => qc.setQueryData(["interview", id], x)} />;
}

function Room({ s, setS }: { s: InterviewSession; setS: (s: InterviewSession) => void }) {
  const who: InterviewerKey = s.meta.interviewer ?? "female";
  const iv = INTERVIEWERS[who];
  const strict = s.meta.strict ?? false;
  const head = useRef<InterviewerHandle>(null);
  const [started, setStarted] = useState(Object.keys(s.answers).length > 0);
  const [muted, setMuted] = useState(false);
  const [speaking, setSpeaking] = useState(false);
  const [feedback, setFeedback] = useState<{ q: Q; sc: Score } | null>(null);
  const [warning, setWarning] = useState<string | null>(null);
  const [fsLost, setFsLost] = useState(false);
  const done = s.status !== "active" || Object.keys(s.scores).length >= s.questions.length;
  const current = s.questions.find((q) => !s.scores[q.id]);

  // ---- integrity (strict mode)
  const report = useMutation({
    mutationFn: (type: IntegrityType) => api.post<InterviewSession>(`/interviews/${s.id}/integrity`, { type, question_id: current?.id ?? null }),
    onSuccess: (r) => setS(r),
  });
  const lastEvent = useRef<Record<string, number>>({});
  const flag = useCallback(
    (type: IntegrityType, message?: string) => {
      if (!strict) return;
      const now = Date.now();
      // tab switches fire both visibilitychange and blur: count one leave per second
      const leave = type === "tab_hidden" || type === "window_blur" || type === "fullscreen_exit";
      const k = leave ? "leave" : type;
      if (now - (lastEvent.current[k] ?? 0) < (leave ? 1500 : 3000)) return;
      lastEvent.current[k] = now;
      report.mutate(type);
      if (message) setWarning(message);
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [strict, s.id, current?.id],
  );
  const live = started && !done;
  useEffect(() => {
    if (!live || !strict) return;
    const onVis = () => document.hidden && flag("tab_hidden", "You left the interview tab.");
    const onBlur = () => setTimeout(() => !document.hidden && flag("window_blur", "You switched to another window or app."), 150);
    const onFs = () => {
      if (!document.fullscreenElement) {
        setFsLost(true);
        flag("fullscreen_exit", "You exited full screen.");
      } else setFsLost(false);
    };
    const onUnload = (e: BeforeUnloadEvent) => e.preventDefault();
    document.addEventListener("visibilitychange", onVis);
    window.addEventListener("blur", onBlur);
    document.addEventListener("fullscreenchange", onFs);
    window.addEventListener("beforeunload", onUnload);
    return () => {
      document.removeEventListener("visibilitychange", onVis);
      window.removeEventListener("blur", onBlur);
      document.removeEventListener("fullscreenchange", onFs);
      window.removeEventListener("beforeunload", onUnload);
    };
  }, [live, strict, flag]);
  useEffect(() => {
    if (done && document.fullscreenElement) document.exitFullscreen().catch(() => {});
  }, [done]);

  // ---- the interviewer's voice
  const speak = useCallback(
    (text: string, then?: () => void) => {
      if (muted || typeof speechSynthesis === "undefined") {
        then?.();
        return;
      }
      speechSynthesis.cancel();
      const u = new SpeechSynthesisUtterance(text);
      const v = pickVoice(iv);
      if (v) {
        u.voice = v;
        u.lang = v.lang;
      } else u.lang = "en-IN";
      u.pitch = iv.pitch;
      u.rate = 0.98;
      u.onstart = () => {
        setSpeaking(true);
        head.current?.speakStart();
      };
      u.onboundary = (e) => e.name === "word" && head.current?.speakWord();
      const end = () => {
        setSpeaking(false);
        head.current?.speakEnd();
        then?.();
      };
      u.onend = end;
      u.onerror = end;
      speechSynthesis.speak(u);
    },
    [muted, iv],
  );
  useEffect(() => () => speechSynthesis?.cancel(), []);
  useEffect(() => {
    if (typeof speechSynthesis !== "undefined") speechSynthesis.getVoices(); // voices load asynchronously in Chrome
  }, []);

  const start = async () => {
    if (strict) {
      try {
        if (!document.fullscreenEnabled) throw new Error("unsupported");
        await document.documentElement.requestFullscreen({ navigationUI: "hide" });
      } catch {
        // Some browsers (iPhone Safari, in-app browsers) can't go full screen: the interview still runs, and
        // leaving the tab or app is still recorded.
        toast.warning("Full screen isn't available in this browser. Switching tabs or apps is still recorded.");
      }
    }
    setStarted(true);
    api.post<InterviewSession>(`/interviews/${s.id}/start`).then(setS, () => {});
  };

  if (done) return <Report s={s} />;
  if (!started) return <Intro s={s} onStart={start} />;

  const round = s.rounds[current?.round ?? 0];
  const firstOfRound = current && s.questions.find((q) => q.round === current.round)?.id === current.id;
  return (
    <div className="space-y-4">
      {strict && (warning || fsLost) && (
        <div role="alert" className="flex flex-wrap items-center gap-3 rounded-[var(--radius-card)] border border-[color-mix(in_oklab,var(--error)_40%,transparent)] bg-[color-mix(in_oklab,var(--error)_10%,transparent)] p-3 text-[13.5px]">
          <ShieldAlert className="size-4 text-[var(--error)]" />
          <span className="flex-1">
            {warning} Warning {s.integrity.violations} of {s.integrity.max_violations}: at {s.integrity.max_violations} the interview ends.
          </span>
          {fsLost && document.fullscreenEnabled && (
            <Button size="sm" onClick={() => document.documentElement.requestFullscreen().catch(() => {})}>
              <Maximize /> Back to full screen
            </Button>
          )}
          <Button size="sm" variant="ghost" onClick={() => setWarning(null)}>
            Dismiss
          </Button>
        </div>
      )}
      <div className="flex flex-wrap items-center justify-between gap-2 text-[13px] text-text-2">
        <div className="flex flex-wrap items-center gap-2">
          {s.rounds.map((r) => (
            <Badge key={r.index} tone={r.index === round?.index ? "accent" : r.answered === r.total ? "success" : "outline"}>
              {r.answered === r.total && <Check />} {r.name}
            </Badge>
          ))}
        </div>
        <div className="flex items-center gap-2">
          {strict ? (
            <Badge tone="warning">
              <ShieldCheck /> Strict mode
            </Badge>
          ) : (
            <Badge tone="outline">Practice mode</Badge>
          )}
          <Clock30 s={s} />
          <Button size="icon" variant="ghost" aria-label={muted ? "Turn interviewer voice on" : "Mute interviewer"} onClick={() => (setMuted((m) => !m), speechSynthesis?.cancel())}>
            {muted ? <VolumeX className="size-4" /> : <Volume2 className="size-4" />}
          </Button>
        </div>
      </div>
      <div className={cn("grid gap-5", current?.kind === "coding" && !feedback ? "lg:grid-cols-[minmax(0,240px)_minmax(0,1fr)]" : "lg:grid-cols-[minmax(0,440px)_minmax(0,1fr)]")}>
        <div className="space-y-3">
          <Interviewer3D ref={head} who={who} speaking={speaking} />
          <p className="text-center text-[12px] text-text-3">
            {s.meta.job?.title} · {s.meta.job?.company} · {s.meta.industry_name} interview
          </p>
        </div>
        {feedback ? (
          <FeedbackCard
            f={feedback}
            last={!current}
            onNext={() => {
              setFeedback(null);
              head.current?.listen(false);
            }}
          />
        ) : current?.kind === "coding" && current.problem ? (
          <CodingTurn
            key={current.id}
            s={s}
            q={current as Q & { problem: Problem }}
            intro={firstOfRound ? round?.intro : undefined}
            strict={strict}
            speak={speak}
            head={head}
            flag={flag}
            onReviewed={(r) => {
              setS(r);
              const sc = r.scores[current.id];
              setFeedback({ q: current, sc });
              head.current?.nod();
              speak(sc.verdict === "correct" ? "Your solution is correct. Let's look at the review." : "Thanks. Let's go through the review.");
            }}
          />
        ) : current ? (
          <AnswerPanel
            key={current.id}
            s={s}
            q={current}
            roundIntro={firstOfRound ? round?.intro : undefined}
            strict={strict}
            speak={speak}
            speaking={speaking}
            head={head}
            flag={flag}
            onScored={(r, q) => {
              setS(r);
              const sc = r.scores[q.id];
              setFeedback({ q, sc });
              head.current?.nod();
              speak(sc.score >= 4 ? "Good answer. Thank you." : sc.score >= 3 ? "Okay, thank you." : "Alright. Let's move on.");
            }}
          />
        ) : null}
      </div>
    </div>
  );
}

function Intro({ s, onStart }: { s: InterviewSession; onStart: () => void }) {
  const iv = INTERVIEWERS[s.meta.interviewer ?? "female"];
  const strict = s.meta.strict ?? false;
  const [mic, setMic] = useState<MicState>("unknown");
  const [typeOnly, setTypeOnly] = useState(false);
  useEffect(() => {
    // Already allowed on an earlier visit? Then there's nothing to ask.
    navigator.permissions
      ?.query({ name: "microphone" as PermissionName })
      .then((p) => {
        if (p.state === "granted") setMic("granted");
        else if (p.state === "denied") setMic("denied");
      })
      .catch(() => {});
  }, []);
  const askMic = async () => {
    const r = await requestMic();
    setMic(r);
    if (r === "denied") toast.error("Microphone blocked. Allow it from the icon in the address bar, or continue and type your answers.");
  };
  const canStart = mic === "granted" || typeOnly || mic === "unsupported";
  return (
    <div className="grid gap-5 lg:grid-cols-[minmax(0,420px)_minmax(0,1fr)]">
      <Interviewer3D who={iv.key} />
      <Card className="space-y-4 p-5">
        <div>
          <div className="eyebrow text-cobalt-text">{s.meta.industry_name} interview</div>
          <h1 className="font-display mt-1 text-[clamp(24px,3vw,32px)] leading-tight">
            {s.meta.job?.title} at {s.meta.job?.company}
          </h1>
          <p className="mt-2 text-[14px] text-text-2">
            {iv.name}, {iv.role.toLowerCase()}, will take you through {s.rounds.length} rounds and {s.questions.length} questions, like the real process for this kind of role. Answer by typing or speaking.
          </p>
        </div>
        <ol className="space-y-1.5">
          {s.rounds.map((r) => (
            <li key={r.index} className="flex items-center justify-between gap-2 rounded-[var(--radius-control)] border border-border px-3 py-2 text-[13.5px]">
              <span>
                {r.index + 1}. {r.name}
              </span>
              <span className="text-text-3">
                {r.total} question{r.total === 1 ? "" : "s"}
              </span>
            </li>
          ))}
        </ol>
        {strict ? (
          <div className="space-y-2 rounded-[var(--radius-card)] border border-[color-mix(in_oklab,var(--your-turn-fill)_40%,transparent)] bg-[color-mix(in_oklab,var(--your-turn-fill)_8%,transparent)] p-4 text-[13px]">
            <div className="flex items-center gap-2 font-semibold">
              <ShieldCheck className="size-4" /> Strict mode, as in a proctored interview
            </div>
            <ul className="list-disc space-y-1 pl-5 text-text-2">
              <li>The interview runs in full screen.</li>
              <li>Switching tab, window or app, or leaving full screen, is recorded. The 3rd time ends the interview.</li>
              <li>Paste, copy, drag-and-drop and right-click are disabled in the answer box.</li>
              <li>Answers that weren't typed or spoken here (no keystrokes, or impossibly fast) don't count.</li>
            </ul>
            <p className="text-[12px] text-text-3">A web page can't stop you using another device, so these checks detect and record rather than block everything. Your report shows each event.</p>
          </div>
        ) : (
          <p className="text-[13px] text-text-2">Practice mode: no proctoring. Switch to strict mode from the job page for a real-interview feel.</p>
        )}
        <div className="flex flex-wrap gap-2">
          <div className="w-full space-y-2 rounded-[var(--radius-card)] border border-border p-3">
            <div className="flex flex-wrap items-center justify-between gap-2 text-[13.5px]">
              <span className="flex items-center gap-2 font-medium">
                <Mic className="size-4" /> Microphone
                {mic === "granted" && <Badge tone="success">Allowed</Badge>}
                {mic === "denied" && <Badge tone="danger">Blocked</Badge>}
              </span>
              {mic !== "granted" && (
                <Button size="sm" onClick={askMic}>
                  {mic === "denied" ? "Try again" : "Allow microphone"}
                </Button>
              )}
            </div>
            <p className="text-[12.5px] text-text-3">
              {mic === "granted"
                ? "Ready. Press Speak during any answer; your words appear in the answer box as you talk."
                : mic === "unsupported"
                  ? "This browser can't use a microphone, so you'll type your answers."
                  : "Allow the microphone to answer out loud, like a real interview."}
            </p>
            {mic !== "granted" && mic !== "unsupported" && (
              <label className="flex items-center gap-2 text-[12.5px] text-text-2">
                <input type="checkbox" checked={typeOnly} onChange={(e) => setTypeOnly(e.target.checked)} className="size-4 accent-[var(--cobalt)]" />
                Continue without the microphone (type every answer)
              </label>
            )}
          </div>
          <Button variant="primary" size="lg" onClick={onStart} disabled={!canStart}>
            {strict ? <Maximize /> : <ArrowRight />} {strict ? "Enter full screen and start" : "Start interview"}
          </Button>
          <Link href={`/jobs/${s.match_id}`} className={buttonClass({ size: "lg", variant: "ghost" })}>
            Not now
          </Link>
        </div>
        <p className="text-[12px] text-text-3">When you speak, your words show live in the answer box; when you stop, the audio is transcribed accurately by our speech-to-text provider (Whisper on Groq) and not stored. Only your answer text is saved.</p>
      </Card>
    </div>
  );
}

function AnswerPanel({
  s,
  q,
  roundIntro,
  strict,
  speak,
  speaking,
  head,
  flag,
  onScored,
}: {
  s: InterviewSession;
  q: Q;
  roundIntro?: string;
  strict: boolean;
  speak: (t: string, then?: () => void) => void;
  speaking: boolean;
  head: React.RefObject<InterviewerHandle | null>;
  flag: (t: IntegrityType, m?: string) => void;
  onScored: (r: InterviewSession, q: Q) => void;
}) {
  const [text, setText] = useState("");
  const [left, setLeft] = useState(q.seconds ?? 150);
  const [ready, setReady] = useState(false);
  const meta = useRef({ keystrokes: 0, voice_chars: 0, pastes_blocked: 0, started: 0, typed: false, spoke: false });
  const textRef = useRef("");
  textRef.current = text;
  // Spoken text goes straight into the answer box: live words while speaking, then the accurate transcript.
  const base = useRef("");
  const join = (a: string, b: string) => (a.trim() && b.trim() ? `${a.trimEnd()} ${b.trim()}` : `${a}${b}`.trim());
  const dictation = useDictation({
    hint: `${q.q} ${q.jd_line} ${q.skill ?? ""}`,
    onLive: (live) => setText(join(base.current, live)),
    onFinal: (final) => {
      setText(join(base.current, final));
      if (final) {
        meta.current.voice_chars += final.length + 1;
        meta.current.spoke = true;
        head.current?.nod();
      }
    },
  });
  // Flow-style push-to-talk (when accurate transcription is available): the whole take is transcribed, fixed and
  // inserted at the cursor. Otherwise the browser's live captions above are the fallback.
  const taRef = useRef<HTMLTextAreaElement>(null);
  const insertAtCursor = (t: string) => {
    const el = taRef.current;
    const cur = textRef.current;
    const a = el && document.activeElement === el ? el.selectionStart : cur.length;
    const b = el && document.activeElement === el ? el.selectionEnd : cur.length;
    const before = cur.slice(0, a);
    const after = cur.slice(b);
    const glueL = before && !/\s$/.test(before) && !/^\s/.test(t) ? " " : "";
    const glueR = after && !/^\s/.test(after) ? " " : "";
    const next = `${before}${glueL}${t}${glueR}${after}`;
    setText(next);
    meta.current.voice_chars += t.length + 1;
    meta.current.spoke = true;
    head.current?.nod();
    requestAnimationFrame(() => {
      const pos = (before + glueL + t).length;
      el?.focus();
      el?.setSelectionRange(pos, pos);
    });
  };
  const replaceTake = (from: string, to: string) => {
    const cur = textRef.current;
    const i = cur.lastIndexOf(from);
    if (i >= 0) setText(cur.slice(0, i) + to + cur.slice(i + from.length));
  };
  // Flowtype's context: the job, the round and the answer around the cursor (read when you start talking).
  const around = () => {
    const el = taRef.current;
    const cur = textRef.current;
    const a = el && document.activeElement === el ? el.selectionStart : cur.length;
    const b = el && document.activeElement === el ? el.selectionEnd : cur.length;
    return { before: cur.slice(0, a), after: cur.slice(b) };
  };
  const flow = useFlow({
    hint: `${q.q} ${q.jd_line} ${q.skill ?? ""}`,
    active: ready,
    onText: insertAtCursor,
    onReplace: replaceTake,
    context: { company: s.meta.job?.company, role: s.meta.job?.title, roundName: q.round_name, kind: q.kind, around },
    onLearned: (w) => toast.success(`Flowtype learned ${w.slice(0, 3).join(", ")}: spelled your way from now on.`),
  });
  const voice = flow.supported ? flow : dictation;
  const speakToggle = () => {
    if (dictation.listening) return dictation.stop();
    base.current = textRef.current;
    dictation.start();
  };

  // One follow-up per answer, like a trained interviewer: pushback, a new constraint, or "what was your part?".
  const [followUp, setFollowUp] = useState<string | null>(null);
  const probe = useMutation({
    mutationFn: (answer: string) => api.post<{ follow_up: string }>(`/interviews/${s.id}/follow-up`, { question_id: q.id, answer }),
    onSuccess: (r, answer) => {
      if (!r.follow_up) return submit.mutate(answer);
      setFollowUp(r.follow_up);
      setText(`${answer}\n\nFollow-up: ${r.follow_up}\nMy answer: `);
      setLeft((l) => Math.max(l, 0) + 60);
      head.current?.listen(false);
      speak(r.follow_up, () => head.current?.listen(true));
    },
    onError: (_e, answer) => submit.mutate(answer),
  });
  const onSubmit = () => {
    const answer = text.trim();
    if (!followUp && left > 25 && answer.split(/\s+/).length >= 12) probe.mutate(answer);
    else submit.mutate(answer);
  };
  const submit = useMutation({
    mutationFn: (answer: string) => {
      flow.reportEdits(answer); // the Dictation Edit Rate: was the dictated text changed before submitting?
      const m = meta.current;
      return api.post<InterviewSession>(`/interviews/${s.id}/answer`, {
        question_id: q.id,
        answer,
        meta: { mode: m.spoke && m.typed ? "mixed" : m.spoke ? "voice" : "typed", keystrokes: m.keystrokes, voice_chars: m.voice_chars, active_ms: m.started ? Date.now() - m.started : 0, pastes_blocked: m.pastes_blocked, follow_up: followUp },
      });
    },
    onSuccess: (r) => onScored(r, q),
    onError: (e: Error) => toast.error(e.message),
  });

  // Ask the question (with the round intro first), then start the clock.
  useEffect(() => {
    const say = `${roundIntro ? `${roundIntro} ` : ""}${q.q}`;
    speak(say, () => {
      setReady(true);
      meta.current.started = Date.now();
      head.current?.listen(true);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q.id]);
  useEffect(() => {
    if (!ready || submit.isPending || submit.isSuccess) return;
    if (left <= 0) {
      toast("Time's up. Your answer so far was submitted.");
      (voice.listening ? voice.stop() : Promise.resolve()).then(() => submit.mutate(textRef.current.trim() || "(No answer given in time)"));
      return;
    }
    const t = setTimeout(() => setLeft((x) => x - 1), 1000);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, left]);

  const block = (type: IntegrityType, what: string) => (e: ClipboardEvent | DragEvent | React.MouseEvent) => {
    if (!strict) return;
    e.preventDefault();
    if (type === "paste_blocked") meta.current.pastes_blocked++;
    toast.error(`${what} is disabled during a strict interview`);
    flag(type);
  };
  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (strict && (e.metaKey || e.ctrlKey) && ["v", "c", "x"].includes(e.key.toLowerCase())) {
      e.preventDefault();
      if (e.key.toLowerCase() === "v") meta.current.pastes_blocked++;
      toast.error("Copy and paste are disabled during a strict interview");
      flag("shortcut_blocked");
    }
  };
  // Typing is counted from input events, not key presses: phone keyboards report keys as "Unidentified", but
  // every character (or autocorrected word) arrives as a small input event. A single insert of more than 25
  // characters is text dropped in from elsewhere (a paste that slipped through, an autofill or a script), so it
  // doesn't count as typing.
  const onInput = (e: React.FormEvent<HTMLTextAreaElement>) => {
    const ne = e.nativeEvent as InputEvent;
    const kind = ne.inputType ?? "";
    if (kind.startsWith("delete") || kind === "insertLineBreak") meta.current.keystrokes++;
    else if (kind.startsWith("insert") && !kind.startsWith("insertFrom")) {
      const n = (ne.data ?? "").length;
      if (n <= 25) meta.current.keystrokes += Math.max(1, n);
    }
    meta.current.typed = true;
    if (meta.current.keystrokes % 40 === 0) head.current?.nod();
  };
  const idx = s.questions.findIndex((x) => x.id === q.id);
  const total = q.seconds ?? 150;

  return (
    <Card className="flex flex-col">
      <div className="space-y-3 p-5">
        <div className="flex flex-wrap items-center justify-between gap-2 text-[12.5px] text-text-3">
          <span>
            Question {idx + 1} of {s.questions.length} · {q.round_name}
          </span>
          <span className={cn("num inline-flex items-center gap-1", ready && left <= 20 && "text-[var(--error)]")}>
            <Clock className="size-3.5" /> {ready ? fmt(left) : fmt(total)}
          </span>
        </div>
        <p className="text-[18px] leading-relaxed font-medium" aria-live="polite">
          {q.q}
        </p>
        <p className="text-[12.5px] text-text-3">Tests: {q.jd_line}</p>
        <div className="h-1 overflow-hidden rounded-full bg-elevated-2">
          <div className="h-full bg-cobalt transition-[width] duration-1000 ease-linear" style={{ width: `${ready ? (left / total) * 100 : 100}%` }} />
        </div>
      </div>
      <div className="space-y-3 border-t border-border p-5">
        <Textarea
          ref={taRef}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={onKeyDown}
          onInput={onInput}
          onPaste={block("paste_blocked", "Pasting")}
          onDrop={block("drop_blocked", "Dropping text")}
          onCopy={block("copy_blocked", "Copying")}
          onCut={block("copy_blocked", "Cutting")}
          onContextMenu={block("context_menu", "Right-click")}
          rows={8}
          spellCheck={false}
          autoComplete="off"
          disabled={!ready}
          readOnly={voice.listening || voice.transcribing}
          placeholder={ready ? (flow.supported ? "Type, or hold Right Ctrl (Right Option on a Mac) and talk. Let go and your words appear here." : "Type your answer, or press Speak and answer out loud…") : "Listen to the question…"}
          aria-label="Your answer"
          className={cn(voice.listening && "border-[var(--cobalt)]")}
        />
        {followUp && (
          <div className="rounded-[var(--radius-card)] border border-[var(--cobalt)]/40 bg-cobalt-subtle/40 p-3 text-[13.5px]" aria-live="polite">
            <span className="font-medium text-cobalt-text">Follow-up: </span>
            {followUp}
            <span className="mt-1 block text-[12px] text-text-3">Answer it under “My answer:” (speak or type). You have an extra minute; both answers are graded together.</span>
          </div>
        )}
        {flow.supported && ready && !voice.listening && !voice.transcribing && !voice.source && (
          <p className="text-[12px] text-text-3">
            <span className="font-medium text-text-2">Flowtype:</span> <kbd className="rounded border border-border px-1 font-mono text-[11px]">Right Ctrl</kbd> hold to talk · double-tap for hands-free · or hold the Speak button. Long answers are written out while you talk; your name, college and projects are spelled your way, and words you correct are learned.
            <SpeechModeSwitch mode={flow.mode} onChange={flow.setMode} />
          </p>
        )}
        {!voice.listening && !voice.transcribing && voice.source && (
          <p className="text-[12px] text-text-3" aria-live="polite">
            {flow.supported && flow.latencyMs != null && <span className="num mr-1">{(flow.latencyMs / 1000).toFixed(1)} s ·</span>}
            {voice.source !== "whisper"
              ? "Live captions only (the accurate transcriber wasn't available). Read it through and fix any misheard word before you submit."
              : flow.supported && flow.cleaned
                ? "✓ Flowtype polished it: fillers, false starts and self-corrections cleaned up, nothing added. Your name, college and projects are spelled your way."
                : "✓ Flowtype wrote it word for word, with your name, college, projects and skills spelled your way."}
            {flow.supported && flow.cleaned && (
              <button type="button" onClick={flow.restoreExactWords} className="ml-1 text-cobalt-text hover:underline">
                Use my exact words
              </button>
            )}
            {!!voice.corrections.length && (
              <span className="mt-0.5 block">
                Fixed using your profile: {voice.corrections.slice(0, 4).map((c) => `“${c.heard}” → ${c.fixed}`).join(", ")}
              </span>
            )}
            <MyWords />
          </p>
        )}
        {(voice.listening || voice.transcribing || voice.error) && (
          <div className="flex items-center gap-2 text-[12.5px]" aria-live="polite">
            {voice.listening && (
              <>
                <span className="flex h-4 items-end gap-0.5" aria-hidden>
                  {[0.55, 1, 0.75, 0.9, 0.6].map((k, i) => (
                    <span key={i} className="w-1 rounded-full bg-[var(--cobalt)] transition-[height] duration-75" style={{ height: `${Math.max(3, voice.level * k * 16)}px` }} />
                  ))}
                </span>
                <span className="text-text-2">{flow.supported ? (flow.handsFree ? "Hands-free: talk, then press Right Ctrl or Stop." : "Listening… let go when you finish.") : "Listening… speak naturally; press Stop when you finish."}</span>
              </>
            )}
            {voice.transcribing && <span className="text-text-2">Writing it out…</span>}
            {voice.error && <span className="text-[var(--your-turn)]">{voice.error}</span>}
          </div>
        )}
        <div className="flex flex-wrap items-center gap-2">
          {flow.supported ? (
            <Button {...flow.buttonHandlers} aria-pressed={flow.listening} disabled={!ready || flow.transcribing} variant={flow.listening ? "danger" : "secondary"} title="Hold to talk, or tap for hands-free">
              {flow.listening ? <MicOff /> : <Mic />} {flow.listening ? (flow.handsFree ? "Stop" : "Release to finish") : "Hold to speak"}
            </Button>
          ) : (
            <Button onClick={speakToggle} aria-pressed={dictation.listening} disabled={!ready || dictation.transcribing} variant={dictation.listening ? "danger" : "secondary"}>
              {dictation.listening ? <MicOff /> : <Mic />} {dictation.listening ? "Stop speaking" : "Speak"}
            </Button>
          )}
          <Button
            variant="primary"
            loading={submit.isPending || probe.isPending}
            disabled={!text.trim() || !ready || voice.listening || voice.transcribing || probe.isPending}
            onClick={onSubmit}
          >
            {followUp ? "Submit both answers" : "Submit answer"} <ArrowRight />
          </Button>
          {!ready && !speaking && (
            <Button variant="ghost" onClick={() => (setReady(true), (meta.current.started = Date.now()))}>
              Skip to answering
            </Button>
          )}
          <span className="text-[12px] text-text-3">{text.split(/\s+/).filter(Boolean).length} words</span>
        </div>
      </div>
    </Card>
  );
}

function FeedbackCard({ f, last, onNext }: { f: { q: Q; sc: Score }; last: boolean; onNext: () => void }) {
  const { sc } = f;
  if (sc.verdict) return <CodeReviewCard f={f} last={last} onNext={onNext} />;
  return (
    <Card className="space-y-4 p-5">
      <div className="flex items-center gap-4">
        <ScoreRing score={sc.score * 20} size={64} stroke={5} label={false} />
        <div>
          <div className="num text-[22px] font-semibold">{sc.score}/5</div>
          <div className="text-[12.5px] text-text-3">
            Relevance {sc.relevance} · specificity {sc.specificity} · structure {sc.structure}
          </div>
        </div>
      </div>
      {!!sc.integrity_flags?.length && (
        <p className="flex gap-2 text-[13px] text-[var(--error)]">
          <AlertTriangle className="size-4 shrink-0" /> {sc.integrity_flags.join(". ")}.
        </p>
      )}
      <ul className="space-y-1.5 text-[13.5px] text-text-2">
        {sc.feedback.map((x) => (
          <li key={x}>· {x}</li>
        ))}
      </ul>
      <p className="text-[12px] text-text-3">This question tested: {sc.tests}</p>
      <Button variant="primary" onClick={onNext}>
        {last ? "See my report" : "Next question"} <ArrowRight />
      </Button>
    </Card>
  );
}

const VERDICT_TONE: Record<string, "success" | "warning" | "danger" | "outline"> = { correct: "success", "partially correct": "warning", incorrect: "danger", "not verified": "outline" };

/** The AI code reviewer's verdict on one coding answer. */
export function CodeReviewCard({ f, last, onNext }: { f: { q: Q; sc: Score }; last?: boolean; onNext?: () => void }) {
  const { sc } = f;
  const list = (title: string, items?: string[]) =>
    !!items?.length && (
      <div>
        <div className="mb-1 text-[12.5px] font-medium text-text-2">{title}</div>
        <ul className="space-y-1 text-[13px] text-text-2">
          {items.map((x) => (
            <li key={x}>· {x}</li>
          ))}
        </ul>
      </div>
    );
  return (
    <Card className="space-y-4 p-5">
      <div className="flex flex-wrap items-center gap-3">
        <ScoreRing score={sc.score * 20} size={64} stroke={5} label={false} />
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[18px] font-semibold">Code review</span>
            <Badge tone={VERDICT_TONE[sc.verdict ?? ""] ?? "outline"}>{sc.verdict}</Badge>
          </div>
          <div className="text-[12.5px] text-text-3">
            {sc.tests_label} · {sc.language} · {sc.ai ? "AI code reviewer" : "rule-based review (AI unavailable)"}
          </div>
        </div>
      </div>
      {!!sc.integrity_flags?.length && (
        <p className="flex gap-2 text-[13px] text-[var(--error)]">
          <AlertTriangle className="size-4 shrink-0" /> {sc.integrity_flags.join(". ")}.
        </p>
      )}
      {sc.summary && <p className="text-[13.5px]">{sc.summary}</p>}
      <div className="grid grid-cols-2 gap-2 text-[12.5px] sm:grid-cols-4">
        {(["correctness", "efficiency", "quality", "communication"] as const).map((k) => (
          <div key={k} className="rounded-[var(--radius-control)] border border-border px-2.5 py-2">
            <div className="text-text-3 capitalize">{k}</div>
            <div className="num text-[15px] font-semibold">{sc[k] ?? "—"}/5</div>
          </div>
        ))}
      </div>
      {sc.clarification != null && (
        <div className="grid grid-cols-3 gap-2 text-[12.5px]" aria-label="Interview process">
          {(
            [
              ["clarification", "Clarified first"],
              ["design", "Complexity stated"],
              ["testing", "Tested & optimised"],
            ] as const
          ).map(([k, label]) => (
            <div key={k} className="rounded-[var(--radius-control)] border border-border px-2.5 py-2">
              <div className="text-text-3">{label}</div>
              <div className="num text-[15px] font-semibold">{sc[k] ?? "—"}/5</div>
            </div>
          ))}
        </div>
      )}
      <p className="text-[13px] text-text-2">
        Complexity: <span className="num">{sc.time_complexity}</span> time, <span className="num">{sc.space_complexity}</span> space{sc.optimal === false ? " · not the expected optimum" : sc.optimal ? " · optimal" : ""}
      </p>
      {list("Bugs", sc.bugs)}
      {list("Edge cases missed", sc.edge_cases_missed)}
      {list("Code quality", sc.code_quality)}
      {list("How to improve", sc.improvements)}
      {onNext && (
        <Button variant="primary" onClick={onNext}>
          {last ? "See my report" : "Next question"} <ArrowRight />
        </Button>
      )}
    </Card>
  );
}

/** Overall interview clock against the planned length (30, 45 or 60 minutes). */
function Clock30({ s }: { s: InterviewSession }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);
  if (!s.started_at || !s.meta.minutes) return null;
  const used = Math.floor((now - new Date(s.started_at).getTime()) / 1000);
  const over = used > s.meta.minutes * 60;
  return (
    <span className={cn("num inline-flex items-center gap-1 text-[12.5px]", over ? "text-[var(--error)]" : "text-text-2")} title="Time in this interview">
      <Clock className="size-3.5" /> {fmt(used)} / {s.meta.minutes}:00
    </span>
  );
}

/** A coding question: the interviewer reads the problem title, then the editor opens. */
function CodingTurn({
  s,
  q,
  intro,
  strict,
  speak,
  head,
  flag,
  onReviewed,
}: {
  s: InterviewSession;
  q: Q & { problem: Problem };
  intro?: string;
  strict: boolean;
  speak: (t: string, then?: () => void) => void;
  head: React.RefObject<InterviewerHandle | null>;
  flag: (t: IntegrityType, m?: string) => void;
  onReviewed: (r: InterviewSession) => void;
}) {
  const [ready, setReady] = useState(false);
  useEffect(() => {
    speak(`${intro ? `${intro} ` : ""}Here's your problem: ${q.problem.title}. Start by asking me anything that's unclear, then tell me your approach and its complexity before you code.`, () => {
      setReady(true);
      head.current?.listen(true);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q.id]);
  return <CodingPanel sessionId={s.id} q={q} index={s.questions.findIndex((x) => x.id === q.id)} total={s.questions.length} strict={strict} onFlag={(t) => flag(t)} onReviewed={(r) => onReviewed(r as InterviewSession)} ready={ready} say={(t) => speak(t)} />;
}

const EVENT_LABEL: Record<string, string> = {
  tab_hidden: "Left the tab",
  window_blur: "Switched window or app",
  fullscreen_exit: "Left full screen",
  paste_blocked: "Paste blocked",
  copy_blocked: "Copy blocked",
  drop_blocked: "Drop blocked",
  shortcut_blocked: "Shortcut blocked",
  context_menu: "Right-click blocked",
};

function Report({ s }: { s: InterviewSession }) {
  const router = useRouter();
  const apply = useMutation({
    mutationFn: (ids: string[]) => api.post<{ added: string[] }>(`/interviews/${s.id}/apply-skills`, { question_ids: ids }),
    onSuccess: (r) => toast.success(r.added.length ? `Added ${r.added.join(", ")} and re-scored the job` : "Nothing strong enough to add yet"),
  });
  const retake = useMutation({
    mutationFn: () => api.post<InterviewSession>("/interviews", { match_id: s.match_id, interviewer: s.meta.interviewer ?? "female", strict: s.meta.strict ?? true }),
    onSuccess: (r) => router.push(`/interview/${r.id}`),
    onError: (e: Error) => toast.error(e.message),
  });
  const strong = s.questions.filter((x) => x.skill && (s.scores[x.id]?.score ?? 0) >= 4 && !s.scores[x.id]?.integrity_flags?.length).map((x) => x.id);
  const terminated = s.status === "terminated";
  const events = Object.entries(s.integrity.counts);
  return (
    <div className="space-y-4">
      <Card className="p-5">
        <div className="flex flex-wrap items-center gap-5">
          {s.report.score != null ? <ScoreRing score={Math.round(s.report.score * 20)} size={96} stroke={7} /> : <ScoreRing score={0} size={96} stroke={7} />}
          <div className="min-w-0 flex-1">
            <div className="eyebrow text-cobalt-text">{s.meta.industry_name} interview report</div>
            <h1 className="font-display mt-1 text-[clamp(22px,3vw,30px)] leading-tight">{terminated ? "Interview ended" : s.report.verdict}</h1>
            <p className="mt-1 text-[13.5px] text-text-2">
              {s.meta.job?.title} at {s.meta.job?.company} · {s.report.answered} of {s.report.total} answered{s.report.score != null ? ` · average ${s.report.score}/5` : ""}
            </p>
          </div>
        </div>
        {terminated && s.integrity.terminated_reason && (
          <p className="mt-4 flex gap-2 rounded-[var(--radius-card)] border border-[color-mix(in_oklab,var(--error)_40%,transparent)] p-3 text-[13.5px] text-[var(--error)]">
            <ShieldAlert className="size-4 shrink-0" /> {s.integrity.terminated_reason}
          </p>
        )}
        <div className="mt-5 flex flex-wrap gap-2">
          <Button variant="primary" onClick={() => retake.mutate()} loading={retake.isPending}>
            <RotateCcw /> Retake with new questions
          </Button>
          {!!strong.length && (
            <Button onClick={() => apply.mutate(strong)} loading={apply.isPending}>
              Add the skills I showed to my profile
            </Button>
          )}
          <Link href={`/jobs/${s.match_id}`} className={buttonClass({ variant: "ghost" })}>
            Back to the job
          </Link>
        </div>
      </Card>

      <InterviewReport id={s.id} />

      <div className="grid gap-4">
        <Card>
          <CardHeader title="Integrity" description={s.meta.strict ? "Strict mode was on." : "Practice mode: not proctored."} />
          <div className="space-y-2 p-5 pt-3 text-[13.5px]">
            {!events.length ? (
              <p className="flex items-center gap-2 text-[var(--done)]">
                <ShieldCheck className="size-4" /> No events. You stayed in the interview throughout.
              </p>
            ) : (
              events.map(([k, n]) => (
                <div key={k} className="flex justify-between">
                  <span className="text-text-2">{EVENT_LABEL[k] ?? k}</span>
                  <span className="num">{n}</span>
                </div>
              ))
            )}
            {!!s.integrity.flagged_answers.length && <p className="text-[var(--error)]">{s.integrity.flagged_answers.length} answer(s) didn't count: not typed or spoken in the interview.</p>}
          </div>
        </Card>
      </div>

      <Card>
        <CardHeader title="Every answer" description="What each question tested, your score, and how to improve." />
        <div className="divide-y divide-border">
          {s.questions.map((q, i) => {
            const sc = s.scores[q.id];
            return (
              <details key={q.id} className="group px-5 py-3">
                <summary className="flex cursor-pointer items-center justify-between gap-3 text-[13.5px]">
                  <span className="min-w-0">
                    <span className="text-text-3">{i + 1}.</span> {q.q}
                  </span>
                  <Badge tone={!sc ? "outline" : sc.score >= 4 ? "success" : sc.score >= 3 ? "accent" : "warning"} className="num shrink-0">
                    {sc ? `${sc.score}/5` : "Skipped"}
                  </Badge>
                </summary>
                <div className="mt-2 space-y-2 text-[13px]">
                  <p className="text-text-3">Tests: {q.jd_line}</p>
                  {s.answers[q.id] &&
                    (q.kind === "coding" ? (
                      <pre className="num overflow-x-auto rounded-[var(--radius-control)] bg-elevated p-3 text-[12px]">{s.answers[q.id]}</pre>
                    ) : (
                      <p className="rounded-[var(--radius-control)] bg-elevated p-3 whitespace-pre-line">{s.answers[q.id]}</p>
                    ))}
                  {sc?.verdict && <CodeReviewCard f={{ q, sc }} />}
                  {sc?.integrity_flags?.map((f) => (
                    <p key={f} className="text-[var(--error)]">
                      {f}
                    </p>
                  ))}
                  {!sc?.verdict && sc?.feedback.map((f) => (
                    <p key={f} className="text-text-2">
                      · {f}
                    </p>
                  ))}
                </div>
              </details>
            );
          })}
        </div>
      </Card>
    </div>
  );
}


/** Words speech-to-text should always spell your way (a name, a place, a tool). */
function SpeechModeSwitch({ mode, onChange }: { mode: "polished" | "verbatim"; onChange: (m: "polished" | "verbatim") => void }) {
  const opts = [
    { v: "polished" as const, label: "Polished", tip: "Removes um, uh, false starts and self-corrections (“5, no wait, 6” → 6); adds punctuation and lists. Never adds words." },
    { v: "verbatim" as const, label: "Word for word", tip: "Exactly what you said, with only your names and terms spelled right." },
  ];
  return (
    <span className="mt-1 flex items-center gap-1.5" role="radiogroup" aria-label="How your speech is written">
      <span>Write it:</span>
      {opts.map((o) => (
        <button
          key={o.v}
          type="button"
          role="radio"
          aria-checked={mode === o.v}
          title={o.tip}
          onClick={() => onChange(o.v)}
          className={cn("rounded-full border px-2 py-0.5 text-[11.5px]", mode === o.v ? "border-[var(--cobalt)] text-cobalt-text" : "border-border text-text-3 hover:text-text-2")}
        >
          {o.label}
        </button>
      ))}
    </span>
  );
}

function MyWords() {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const words = useQuery({ queryKey: ["stt-words"], queryFn: () => api.get<{ words: string[]; learned?: string[] }>("/stt/words"), enabled: open });
  const forget = useMutation({
    mutationFn: (w: string) => api.put<{ learned: string[] }>("/stt/learned", { words: (words.data?.learned ?? []).filter((x) => x !== w) }),
    onSuccess: () => words.refetch(),
    onError: (e: Error) => toast.error(e.message),
  });
  const save = useMutation({
    mutationFn: (list: string[]) => api.put<{ words: string[] }>("/stt/words", { words: list }),
    onSuccess: (r) => (words.refetch(), setText(""), toast.success(`Saved. ${r.words.length} word${r.words.length === 1 ? "" : "s"} will be spelled your way.`)),
    onError: (e: Error) => toast.error(e.message),
  });
  if (!open)
    return (
      <button type="button" onClick={() => setOpen(true)} className="mt-0.5 block text-cobalt-text hover:underline">
        A word still comes out wrong? Add it
      </button>
    );
  const add = () => {
    const fresh = text.split(",").map((w) => w.trim()).filter(Boolean);
    if (fresh.length) save.mutate([...(words.data?.words ?? []), ...fresh]);
  };
  return (
    <span className="mt-1.5 flex flex-wrap items-center gap-1.5">
      <input
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && (e.preventDefault(), add())}
        placeholder="e.g. Sidhpurwala, Rizvi College, LangGraph"
        aria-label="Words to spell your way"
        className="h-8 w-64 rounded-[var(--radius-control)] border border-border bg-transparent px-2.5 text-[12.5px] text-text outline-none focus:border-[var(--cobalt)]"
      />
      <Button size="sm" onClick={add} loading={save.isPending}>
        Add
      </Button>
      {!!words.data?.words.length && <span className="text-text-3">Yours: {words.data.words.slice(0, 8).join(", ")}{words.data.words.length > 8 ? "…" : ""}</span>}
      {!!words.data?.learned?.length && (
        <span className="flex flex-wrap items-center gap-1 text-text-3">
          Learned from your corrections:
          {words.data.learned.slice(0, 8).map((w) => (
            <button key={w} type="button" onClick={() => forget.mutate(w)} title="Forget this spelling" className="rounded-full border border-border px-1.5 hover:text-text-2">
              {w} ×
            </button>
          ))}
        </span>
      )}
    </span>
  );
}

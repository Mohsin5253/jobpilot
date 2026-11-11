"use client";

import { cpp } from "@codemirror/lang-cpp";
import { java } from "@codemirror/lang-java";
import { javascript } from "@codemirror/lang-javascript";
import { python } from "@codemirror/lang-python";
import { EditorView } from "@codemirror/view";
import { oneDark } from "@codemirror/theme-one-dark";
import { useMutation } from "@tanstack/react-query";
import CodeMirror from "@uiw/react-codemirror";
import { ArrowRight, CheckCircle2, Clock, HelpCircle, Play, Send, XCircle } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input, Textarea } from "@/components/ui/input";
import { api } from "@/lib/api";
import { RUNNABLE, runTests, type Lang, type RunResult, type Test } from "@/lib/code-runner";
import { cn } from "@/lib/utils";

export interface Problem {
  id: string;
  title: string;
  difficulty: "easy" | "medium" | "hard";
  tags: string[];
  statement: string;
  fn: { python: string; javascript: string };
  params: string[];
  starter: Record<Lang, string>;
  tests: Test[];
  compare: string;
  minutes: number;
}

const LANGS: { value: Lang; label: string }[] = [
  { value: "python", label: "Python" },
  { value: "javascript", label: "JavaScript" },
  { value: "java", label: "Java" },
  { value: "cpp", label: "C++" },
];
const EXT = { python: python(), javascript: javascript(), java: java(), cpp: cpp() };
const DIFF_TONE = { easy: "success", medium: "warning", hard: "danger" } as const;
const fmt = (s: number) => `${Math.floor(Math.max(0, s) / 60)}:${String(Math.max(0, s) % 60).padStart(2, "0")}`;
const show = (v: unknown) => (v === undefined ? "—" : JSON.stringify(v));

type Stage = "clarify" | "design" | "code" | "test";
const STAGES: { key: Stage; label: string }[] = [
  { key: "clarify", label: "Clarify" },
  { key: "design", label: "Approach & complexity" },
  { key: "code", label: "Code" },
  { key: "test", label: "Test & optimise" },
];

/**
 * The coding round, run the way large-tech coding interviews are: clarify the problem (the interviewer answers),
 * state the approach with its time and space complexity, implement it (the editor unlocks only then), then test and
 * optimise your own code. Submit runs every test and sends the code, the results and each stage to the reviewer;
 * skipping a stage costs process points, as it would with a real interviewer.
 */
export function CodingPanel({
  sessionId,
  q,
  index,
  total,
  strict,
  onFlag,
  onReviewed,
  ready,
  say,
}: {
  sessionId: string;
  q: { id: string; round_name: string; seconds?: number; problem: Problem };
  index: number;
  total: number;
  strict: boolean;
  onFlag: (type: "paste_blocked" | "copy_blocked" | "drop_blocked" | "shortcut_blocked" | "context_menu") => void;
  onReviewed: (s: unknown) => void;
  ready: boolean;
  say?: (text: string) => void;
}) {
  const p = q.problem;
  const [lang, setLang] = useState<Lang>("python");
  const [drafts, setDrafts] = useState<Record<Lang, string>>(() => ({ ...p.starter }));
  const [approach, setApproach] = useState("");
  const [run, setRun] = useState<RunResult | null>(null);
  const [running, setRunning] = useState(false);
  const [left, setLeft] = useState(q.seconds ?? p.minutes * 60);
  const meta = useRef({ keystrokes: 0, pastes_blocked: 0, started: Date.now() });
  const [stage, setStage] = useState<Stage>("clarify");
  const stageAt = useRef({ at: Date.now(), ms: {} as Record<string, number> });
  const go = (next: Stage) => {
    const now = Date.now();
    stageAt.current.ms[stage] = (stageAt.current.ms[stage] ?? 0) + now - stageAt.current.at;
    stageAt.current.at = now;
    setStage(next);
  };
  const [clarifications, setClarifications] = useState<{ q: string; a: string }[]>([]);
  const [ask, setAsk] = useState("");
  const [timeC, setTimeC] = useState("");
  const [spaceC, setSpaceC] = useState("");
  const [testNotes, setTestNotes] = useState("");
  const clarify = useMutation({
    mutationFn: (question: string) => api.post<{ answer: string }>(`/interviews/${sessionId}/clarify`, { question_id: q.id, question }),
    onSuccess: (r, question) => {
      setClarifications((c) => [...c, { q: question, a: r.answer }]);
      setAsk("");
      say?.(r.answer);
    },
    onError: (e: Error) => toast.error(e.message),
  });
  const coding = stage === "code" || stage === "test";
  const code = drafts[lang];
  const visible = p.tests.filter((t) => t.visible);

  const submit = useMutation({
    mutationFn: async () => {
      const all = RUNNABLE.includes(lang) ? await runTests({ lang, code, fn: p.fn[lang as "python" | "javascript"], tests: p.tests, compare: p.compare }) : { ran: false, passed: 0, total: p.tests.length, outcomes: [], ms: 0 };
      setRun(all as RunResult);
      const failures = (all.outcomes ?? []).filter((o) => !o.pass).slice(0, 8).map((o) => ({ args: o.args, expected: o.expected, got: o.got ?? null, error: o.error ?? (all as RunResult).error ?? null }));
      return api.post<unknown>(`/interviews/${sessionId}/code`, {
        question_id: q.id,
        language: lang,
        code,
        approach,
        results: { ran: all.ran, passed: all.passed, total: all.total, failures, runtime_ms: all.ms },
        process: { clarifications, time_complexity: timeC, space_complexity: spaceC, test_notes: testNotes, stage_ms: { ...stageAt.current.ms, [stage]: (stageAt.current.ms[stage] ?? 0) + Date.now() - stageAt.current.at } },
        meta: { mode: "typed", keystrokes: meta.current.keystrokes, voice_chars: 0, active_ms: Date.now() - meta.current.started, pastes_blocked: meta.current.pastes_blocked },
      });
    },
    onSuccess: (s) => onReviewed(s),
    onError: (e: Error) => toast.error(e.message),
  });

  useEffect(() => {
    if (!ready || submit.isPending || submit.isSuccess) return;
    if (left <= 0) {
      toast("Time's up. Your code was submitted for review.");
      submit.mutate();
      return;
    }
    const t = setTimeout(() => setLeft((x) => x - 1), 1000);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, left]);

  const runSamples = async () => {
    if (!RUNNABLE.includes(lang)) return toast("Java and C++ can't run in the browser. Submit for an AI review instead.");
    setRunning(true);
    try {
      setRun(await runTests({ lang, code, fn: p.fn[lang as "python" | "javascript"], tests: visible, compare: p.compare }));
    } finally {
      setRunning(false);
    }
  };

  // Strict mode: no paste, drop or copy in the editor; typing is counted from real edits (a single insert of more
  // than 25 characters isn't typing).
  const extensions = useMemo(
    () => [
      EXT[lang],
      EditorView.lineWrapping,
      EditorView.updateListener.of((u) => {
        for (const tr of u.transactions) {
          if (tr.isUserEvent("input.type") || tr.isUserEvent("input.complete") || tr.isUserEvent("delete")) {
            let n = 0;
            tr.changes.iterChanges((_a, _b, _c, _d, ins) => (n += ins.length));
            if (n <= 25) meta.current.keystrokes += Math.max(1, n);
          }
        }
      }),
      EditorView.domEventHandlers({
        paste: (e) => {
          if (!strict) return false;
          e.preventDefault();
          meta.current.pastes_blocked++;
          toast.error("Pasting is disabled during a strict interview");
          onFlag("paste_blocked");
          return true;
        },
        drop: (e) => {
          if (!strict) return false;
          e.preventDefault();
          onFlag("drop_blocked");
          return true;
        },
        copy: (e) => {
          if (!strict) return false;
          e.preventDefault();
          onFlag("copy_blocked");
          return true;
        },
        cut: (e) => {
          if (!strict) return false;
          e.preventDefault();
          onFlag("copy_blocked");
          return true;
        },
        contextmenu: (e) => {
          if (!strict) return false;
          e.preventDefault();
          return true;
        },
      }),
    ],
    [lang, strict, onFlag],
  );

  return (
    <Card className="flex min-w-0 flex-col">
      <div className="space-y-3 p-5">
        <div className="flex flex-wrap items-center justify-between gap-2 text-[12.5px] text-text-3">
          <span>
            Question {index + 1} of {total} · {q.round_name}
          </span>
          <span className={cn("num inline-flex items-center gap-1", ready && left <= 120 && "text-[var(--error)]")}>
            <Clock className="size-3.5" /> {fmt(left)}
          </span>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-[18px] font-semibold">{p.title}</h2>
          <Badge tone={DIFF_TONE[p.difficulty]}>{p.difficulty}</Badge>
          {p.tags.map((t) => (
            <Badge key={t} tone="outline">
              {t}
            </Badge>
          ))}
        </div>
        <p className="text-[14px] leading-relaxed whitespace-pre-line text-text-2">{p.statement}</p>
        <div className="space-y-1.5">
          {visible.map((t, i) => (
            <div key={i} className="num rounded-[var(--radius-control)] bg-elevated px-3 py-2 text-[12.5px] break-all">
              <span className="text-text-3">{p.fn[lang === "javascript" ? "javascript" : "python"]}(</span>
              {t.args.map((a) => show(a)).join(", ")}
              <span className="text-text-3">) → </span>
              {show(t.expected)}
            </div>
          ))}
        </div>
      </div>
      <div className="space-y-3 border-t border-border p-5">
        <ol className="flex flex-wrap gap-1.5" aria-label="Interview stages">
          {STAGES.map((st, i) => {
            const at = STAGES.findIndex((x) => x.key === stage);
            return (
              <li key={st.key} aria-current={st.key === stage ? "step" : undefined} className={cn("rounded-full border px-2.5 py-0.5 text-[12px]", st.key === stage ? "border-[var(--cobalt)] bg-cobalt-subtle font-medium text-cobalt-text" : i < at ? "border-border text-success" : "border-border text-text-3")}>
                {i < at ? "✓ " : `${i + 1}. `}
                {st.label}
              </li>
            );
          })}
        </ol>
        {stage === "clarify" && (
          <div className="space-y-2.5 rounded-[var(--radius-card)] border border-border p-3">
            <p className="text-[13px] text-text-2">
              <HelpCircle className="mr-1 inline size-3.5" />
              Before designing, ask the interviewer about anything unclear: input size, empty input, duplicates, negatives, output format. Interviewers note candidates who start coding without asking.
            </p>
            {clarifications.map((c, i) => (
              <div key={i} className="text-[13px]">
                <div>
                  <span className="text-text-3">You:</span> {c.q}
                </div>
                <div>
                  <span className="text-cobalt-text">Interviewer:</span> {c.a}
                </div>
              </div>
            ))}
            <div className="flex gap-2">
              <Input value={ask} onChange={(e) => setAsk(e.target.value)} onKeyDown={(e) => e.key === "Enter" && ask.trim().length > 2 && clarify.mutate(ask.trim())} placeholder="e.g. Can the list be empty? How large can n get?" aria-label="Clarifying question" disabled={!ready} />
              <Button onClick={() => clarify.mutate(ask.trim())} loading={clarify.isPending} disabled={!ready || ask.trim().length < 3}>
                Ask
              </Button>
            </div>
            <Button variant="primary" disabled={!ready} onClick={() => (clarifications.length || toast("Moving on without clarifying: that's noted, as a real interviewer would."), go("design"))}>
              Continue to approach <ArrowRight />
            </Button>
          </div>
        )}
        {stage === "design" && (
          <div className="space-y-2.5 rounded-[var(--radius-card)] border border-border p-3">
            <p className="text-[13px] text-text-2">Say the brute force and its cost, then your better approach. The editor unlocks once you&rsquo;ve stated the time complexity.</p>
            <Textarea
              value={approach}
              onChange={(e) => setApproach(e.target.value)}
              onPaste={(e) => {
                if (strict) {
                  e.preventDefault();
                  onFlag("paste_blocked");
                }
              }}
              rows={3}
              placeholder="Brute force: … O(n²). Better: … because …. Edge cases: …"
              aria-label="Your approach"
            />
            <div className="grid gap-2 sm:grid-cols-2">
              <Input value={timeC} onChange={(e) => setTimeC(e.target.value)} placeholder="Time, e.g. O(n)" aria-label="Time complexity" />
              <Input value={spaceC} onChange={(e) => setSpaceC(e.target.value)} placeholder="Space, e.g. O(n)" aria-label="Space complexity" />
            </div>
            <Button variant="primary" disabled={approach.trim().split(/\s+/).length < 4 || !timeC.trim()} onClick={() => (say?.("Sounds good. Go ahead and code it."), go("code"))}>
              Start coding <ArrowRight />
            </Button>
          </div>
        )}
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex flex-wrap gap-1" role="radiogroup" aria-label="Language">
            {LANGS.map((l) => (
              <button
                key={l.value}
                type="button"
                role="radio"
                aria-checked={lang === l.value}
                onClick={() => setLang(l.value)}
                className={cn("h-8 rounded-[var(--radius-control)] border px-3 text-[12.5px]", lang === l.value ? "border-[var(--cobalt)] bg-cobalt-subtle text-cobalt-text" : "border-border text-text-2 hover:text-text")}
              >
                {l.label}
              </button>
            ))}
          </div>
          {!RUNNABLE.includes(lang) && <span className="text-[12px] text-text-3">Runs in AI review only</span>}
        </div>
        <div className="overflow-hidden rounded-[var(--radius-control)] border border-border text-[13.5px]">
          <CodeMirror
            value={code}
            height="300px"
            theme={oneDark}
            extensions={extensions}
            onChange={(v) => setDrafts((d) => ({ ...d, [lang]: v }))}
            basicSetup={{ lineNumbers: true, foldGutter: false, highlightActiveLine: true, autocompletion: false }}
            aria-label="Code editor"
            editable={ready && coding}
          />
        </div>
        {stage === "test" && (
          <Textarea
            value={testNotes}
            onChange={(e) => setTestNotes(e.target.value)}
            onPaste={(e) => {
              if (strict) {
                e.preventDefault();
                onFlag("paste_blocked");
              }
            }}
            rows={3}
            placeholder="Test your own code: walk through an edge case (empty, duplicates, large n). Any bug you found? What would you optimise next?"
            aria-label="Testing and optimisation notes"
          />
        )}
        <div className="flex flex-wrap items-center gap-2">
          <Button onClick={runSamples} loading={running} disabled={!ready || !coding || !RUNNABLE.includes(lang)}>
            <Play /> Run sample tests
          </Button>
          {stage === "code" && (
            <Button variant="primary" disabled={!ready} onClick={() => (say?.("Now test it. Walk me through an edge case, and tell me what you'd optimise."), go("test"))}>
              Next: test & optimise <ArrowRight />
            </Button>
          )}
          {stage === "test" && (
            <Button variant="primary" onClick={() => submit.mutate()} loading={submit.isPending} disabled={!ready}>
              <Send /> Submit for review
            </Button>
          )}
          {!coding && <span className="text-[12px] text-text-3">The editor unlocks after the approach stage.</span>}
          {lang === "python" && !run && <span className="text-[12px] text-text-3">First Python run loads the interpreter (a few seconds).</span>}
        </div>
        {run && <RunOutput r={run} />}
      </div>
    </Card>
  );
}

function RunOutput({ r }: { r: RunResult }) {
  return (
    <div className="space-y-2 rounded-[var(--radius-card)] border border-border p-3 text-[13px]">
      <div className="flex items-center gap-2 font-medium">
        {r.passed === r.total && r.total ? <CheckCircle2 className="size-4 text-[var(--done)]" /> : <XCircle className="size-4 text-[var(--error)]" />}
        {r.passed}/{r.total} tests passed <span className="text-[12px] font-normal text-text-3">· {r.ms} ms</span>
      </div>
      {r.error && <pre className="overflow-x-auto rounded bg-elevated p-2 text-[12px] whitespace-pre-wrap text-[var(--error)]">{r.error}</pre>}
      {r.outcomes
        .filter((o) => !o.pass)
        .slice(0, 3)
        .map((o) => (
          <div key={o.index} className="num rounded bg-elevated p-2 text-[12px] break-all">
            {o.visible ? (
              <>
                <div>input: {o.args.map((a) => show(a)).join(", ")}</div>
                <div>expected: {show(o.expected)}</div>
              </>
            ) : (
              <div className="text-text-3">Hidden test #{o.index + 1}</div>
            )}
            <div className="text-[var(--error)]">{o.error ? o.error : `got: ${show(o.got)}`}</div>
            {o.stdout && <div className="text-text-3">printed: {o.stdout}</div>}
          </div>
        ))}
    </div>
  );
}

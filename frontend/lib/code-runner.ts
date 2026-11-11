/**
 * Runs interview code in the browser, never on our servers.
 *
 * Isolation: the runner lives in an <iframe sandbox="allow-scripts" srcdoc> (an opaque origin: no cookies, no
 * storage, and requests to our API carry no credentials), and the candidate's code runs in a Web Worker started from
 * a blob URL, so an infinite loop is ended by terminating the worker. JavaScript is loaded with importScripts (no
 * eval); Python runs on Pyodide (CPython in WebAssembly) from jsDelivr, cached by the browser after the first load.
 * Java and C++ can't run here and go to the AI reviewer only.
 */

export type Lang = "python" | "javascript" | "java" | "cpp";
export const RUNNABLE: Lang[] = ["python", "javascript"];
const PYODIDE = "https://cdn.jsdelivr.net/pyodide/v0.26.4/full/";

export interface Test {
  args: unknown[];
  expected: unknown;
  visible: boolean;
}
export interface TestOutcome {
  index: number;
  pass: boolean;
  args: unknown[];
  expected: unknown;
  got?: unknown;
  error?: string;
  ms?: number;
  stdout?: string;
  visible: boolean;
}
export interface RunResult {
  ran: boolean;
  passed: number;
  total: number;
  outcomes: TestOutcome[];
  error?: string;
  timedOut?: boolean;
  ms: number;
}

const PY_HARNESS = [
  "import json, copy, time, io, contextlib",
  "_ns = {}",
  "_res = []",
  "_err = None",
  "try:",
  "    exec(USER_CODE, _ns)",
  "    _f = _ns.get(FN)",
  "    if not callable(_f):",
  "        raise NameError('function ' + FN + ' is not defined')",
  "except Exception as _e:",
  "    _err = type(_e).__name__ + ': ' + str(_e)",
  "if _err is None:",
  "    for _t in json.loads(TESTS_JSON):",
  "        _buf = io.StringIO()",
  "        _st = time.perf_counter()",
  "        try:",
  "            with contextlib.redirect_stdout(_buf):",
  "                _got = _f(*copy.deepcopy(_t['args']))",
  "            if isinstance(_got, tuple):",
  "                _got = list(_got)",
  "            if isinstance(_got, set):",
  "                _got = sorted(_got)",
  "            _res.append({'got': _got, 'ms': round((time.perf_counter() - _st) * 1000, 2), 'stdout': _buf.getvalue()[-500:]})",
  "        except Exception as _e:",
  "            _res.append({'error': type(_e).__name__ + ': ' + str(_e), 'stdout': _buf.getvalue()[-500:]})",
  "json.dumps({'results': _res, 'error': _err}, default=str)",
].join("\n");

// The worker: Python through Pyodide; JavaScript by importing the code as a script (blob URL), then calling it.
const WORKER_SRC = `
var PYODIDE = ${JSON.stringify(PYODIDE)};
var HARNESS = ${JSON.stringify(PY_HARNESS)};
var py = null;
function errText(e) { return e && e.name ? e.name + ": " + e.message : String(e); }
self.onmessage = async function (e) {
  var job = e.data;
  try {
    if (job.lang === "python") {
      var t0 = Date.now();
      if (!py) { importScripts(PYODIDE + "pyodide.js"); py = await loadPyodide({ indexURL: PYODIDE }); }
      py.globals.set("USER_CODE", job.code); py.globals.set("FN", job.fn); py.globals.set("TESTS_JSON", JSON.stringify(job.tests));
      var out = JSON.parse(py.runPython(HARNESS));
      out.loadMs = Date.now() - t0;
      self.postMessage(out);
      return;
    }
    var src = job.code + "\\n;self.__candidate = (typeof " + job.fn + " !== 'undefined') ? " + job.fn + " : undefined;";
    var url = URL.createObjectURL(new Blob([src], { type: "text/javascript" }));
    try { importScripts(url); } catch (err) { self.postMessage({ error: errText(err), results: [] }); return; } finally { URL.revokeObjectURL(url); }
    var f = self.__candidate;
    if (typeof f !== "function") { self.postMessage({ error: "ReferenceError: function " + job.fn + " is not defined", results: [] }); return; }
    var results = [];
    for (var i = 0; i < job.tests.length; i++) {
      var logs = []; var orig = console.log; console.log = function () { logs.push(Array.prototype.join.call(arguments, " ")); };
      var st = performance.now();
      try {
        var got = f.apply(null, JSON.parse(JSON.stringify(job.tests[i].args)));
        if (got instanceof Set) got = Array.from(got).sort();
        results.push({ got: got === undefined ? null : got, ms: Math.round((performance.now() - st) * 100) / 100, stdout: logs.join("\\n").slice(-500) });
      } catch (err) { results.push({ error: errText(err), stdout: logs.join("\\n").slice(-500) }); }
      console.log = orig;
    }
    self.postMessage({ results: results });
  } catch (err) { self.postMessage({ error: "Runner: " + errText(err), results: [] }); }
};`;

// The sandboxed page: starts a worker per run (Python keeps one, since Pyodide takes seconds to load) and kills it
// on timeout.
const RUNNER_SRC = `
(function () {
  var workerUrl = URL.createObjectURL(new Blob([${JSON.stringify(WORKER_SRC)}], { type: "text/javascript" }));
  var pyWorker = null, pyReady = false;
  function run(job, reply) {
    var w = job.lang === "python" ? pyWorker || (pyWorker = new Worker(workerUrl)) : new Worker(workerUrl);
    var done = false;
    var limit = job.timeoutMs + (job.lang === "python" && !pyReady ? 60000 : 0);
    function finish(out) { if (done) return; done = true; clearTimeout(timer); reply(out); }
    var timer = setTimeout(function () {
      w.terminate();
      if (w === pyWorker) { pyWorker = null; pyReady = false; }
      finish({ id: job.id, results: [], timedOut: true, error: "Time limit exceeded: your code took longer than " + Math.round(job.timeoutMs / 1000) + "s (an infinite loop, or a much slower approach than expected)." });
    }, limit);
    w.onmessage = function (e) {
      if (job.lang !== "python") w.terminate(); else pyReady = true;
      var out = e.data || {}; out.id = job.id; finish(out);
    };
    w.onerror = function (e) {
      w.terminate();
      if (w === pyWorker) { pyWorker = null; pyReady = false; }
      finish({ id: job.id, results: [], error: "Runner error: " + (e.message || "the code could not start") });
    };
    w.postMessage(job);
  }
  window.addEventListener("message", function (e) {
    var job = e.data;
    if (!job || job.type !== "run" || e.source !== window.parent) return;
    run(job, function (out) { out.type = "result"; window.parent.postMessage(out, "*"); });
  });
  window.parent.postMessage({ type: "ready" }, "*");
})();`;

let frame: HTMLIFrameElement | null = null;
let ready: Promise<void> | null = null;
let seq = 0;
const pending = new Map<number, (r: Record<string, unknown>) => void>();

function ensureFrame(): Promise<void> {
  if (ready && frame?.isConnected) return ready;
  frame?.remove();
  const f = document.createElement("iframe");
  frame = f;
  f.setAttribute("sandbox", "allow-scripts"); // no allow-same-origin: the code can't touch the app or its session
  f.setAttribute("aria-hidden", "true");
  f.tabIndex = -1;
  f.style.cssText = "position:absolute;width:0;height:0;border:0;visibility:hidden";
  ready = new Promise((resolve) => {
    window.addEventListener("message", (e: MessageEvent) => {
      if (e.source !== f.contentWindow) return;
      const d = e.data as { type?: string; id?: number };
      if (d?.type === "ready") resolve();
      else if (d?.type === "result" && typeof d.id === "number") {
        pending.get(d.id)?.(d as Record<string, unknown>);
        pending.delete(d.id);
      }
    });
  });
  f.srcdoc = `<!doctype html><meta charset="utf-8"><script>${RUNNER_SRC.replace(/<\/script/gi, "<\\/script")}</script>`;
  document.body.appendChild(f);
  return ready;
}

/** Deep equality the way the tests define it: exact, or within 0.001 for "float" problems. */
export function same(expected: unknown, got: unknown, mode: string): boolean {
  if (mode === "float") {
    if (Array.isArray(expected)) return Array.isArray(got) && got.length === expected.length && expected.every((v, i) => typeof got[i] === "number" && Math.abs((v as number) - got[i]) <= 1e-3);
    return typeof got === "number" && Math.abs((expected as number) - got) <= 1e-3;
  }
  return JSON.stringify(normalize(expected)) === JSON.stringify(normalize(got));
}
function normalize(v: unknown): unknown {
  if (v === undefined) return null;
  if (Array.isArray(v)) return v.map(normalize);
  if (v && typeof v === "object") return Object.fromEntries(Object.entries(v as Record<string, unknown>).sort(([a], [b]) => a.localeCompare(b)).map(([k, x]) => [k, normalize(x)]));
  return v;
}

export async function runTests({ lang, code, fn, tests, compare, timeoutMs = 6000 }: { lang: Lang; code: string; fn: string; tests: Test[]; compare: string; timeoutMs?: number }): Promise<RunResult> {
  const t0 = performance.now();
  if (!RUNNABLE.includes(lang)) return { ran: false, passed: 0, total: tests.length, outcomes: [], ms: 0, error: "Java and C++ can't run in the browser. The AI reviewer will judge your code by reading it." };
  await ensureFrame();
  const id = ++seq;
  const reply = await new Promise<Record<string, unknown>>((resolve) => {
    pending.set(id, resolve);
    frame!.contentWindow!.postMessage({ type: "run", id, lang, code, fn, tests: tests.map((t) => ({ args: t.args })), timeoutMs }, "*");
  });
  const results = (reply.results as { got?: unknown; error?: string; ms?: number; stdout?: string }[]) ?? [];
  const outcomes: TestOutcome[] = tests.map((t, i) => {
    const r = results[i];
    return { index: i, args: t.args, expected: t.expected, visible: t.visible, got: r?.got, error: r?.error, ms: r?.ms, stdout: r?.stdout, pass: !!r && !r.error && same(t.expected, r.got, compare) };
  });
  const error = (reply.error as string | null) ?? undefined;
  // A compile error or a timeout still counts as a run: the code was executed and failed.
  return { ran: true, passed: outcomes.filter((o) => o.pass).length, total: tests.length, outcomes, error, timedOut: !!reply.timedOut, ms: Math.round(performance.now() - t0) };
}

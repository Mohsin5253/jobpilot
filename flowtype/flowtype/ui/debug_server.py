"""The debug panel: a local web page (http://127.0.0.1:8765) with every recent dictation's stage-by-stage latency,
p50/p95 per stage, guard and clean-up outcomes, Edit Rate by mode, the dictionary, and (with store_text on) history.

It listens on 127.0.0.1 only, is read-only, and rejects requests whose Host header isn't local (DNS rebinding)."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from flowtype.store.db import STAGES, Store

PAGE = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Flowtype debug</title><style>
:root{--bg:#fafafa;--fg:#18181b;--mut:#71717a;--line:#e4e4e7;--card:#fff}
@media (prefers-color-scheme:dark){:root{--bg:#111113;--fg:#ededef;--mut:#a1a1aa;--line:#2e2e32;--card:#18181b}}
body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.45 system-ui,sans-serif;padding:16px}
h1{font-size:18px;margin:0 0 12px}h2{font-size:14px;margin:20px 0 8px;color:var(--mut);text-transform:uppercase;letter-spacing:.04em}
table{border-collapse:collapse;width:100%;background:var(--card);border:1px solid var(--line);border-radius:8px;overflow:hidden}
td,th{padding:6px 8px;border-bottom:1px solid var(--line);text-align:left;font-variant-numeric:tabular-nums;vertical-align:top}
th{color:var(--mut);font-weight:500}.bar{display:flex;height:12px;min-width:240px;border-radius:3px;overflow:hidden;background:var(--line)}
.bar span{display:block;height:100%}.k{display:inline-flex;align-items:center;gap:4px;margin-right:10px;color:var(--mut);font-size:12px}
.k i{width:10px;height:10px;border-radius:2px;display:inline-block}.wrap{overflow-x:auto}.ok{color:#30a46c}.bad{color:#e5484d}
</style></head><body><h1>Flowtype debug panel</h1><div id="legend"></div>
<h2>Latency per stage (pasted dictations)</h2><div class="wrap"><table id="summary"></table></div>
<h2>Recent dictations</h2><div class="wrap"><table id="recent"></table></div>
<h2>Edit Rate by clean-up outcome</h2><div class="wrap"><table id="edit"></table></div>
<h2>Dictionary</h2><div class="wrap"><table id="words"></table></div>
<h2>History</h2><div class="wrap"><table id="history"></table></div>
<script>
const C={postroll_ms:"#8b8d98",vad_ms:"#3e63dd",prompt_ms:"#0090ff",asr_ms:"#8e4ec6",asr_retry_ms:"#d6409f",guard_ms:"#e5484d",dictionary_ms:"#f76b15",llm_ms:"#ffc53d",context_ms:"#30a46c",inject_ms:"#12a594"};
const esc=s=>String(s??"").replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
document.getElementById("legend").innerHTML=Object.entries(C).map(([k,c])=>`<span class="k"><i style="background:${c}"></i>${k.replace("_ms","")}</span>`).join("");
async function j(u){const r=await fetch(u);return r.json()}
async function load(){
 const s=await j("/api/summary");
 document.getElementById("summary").innerHTML="<tr><th>stage</th><th>p50 ms</th><th>p95 ms</th><th>n</th></tr>"+Object.entries(s).map(([k,v])=>`<tr><td>${k}</td><td>${v.p50}</td><td>${v.p95}</td><td>${v.n}</td></tr>`).join("");
 const d=await j("/api/dictations?limit=50");
 document.getElementById("recent").innerHTML="<tr><th>#</th><th>when</th><th>app · style</th><th>status</th><th>total</th><th>stages</th><th>ASR</th><th>clean-up</th><th>guard</th><th>edit</th></tr>"+d.map(r=>{
  const tot=Object.keys(C).reduce((a,k)=>a+(r[k]||0),0)||1;
  const bar=Object.keys(C).filter(k=>r[k]).map(k=>`<span title="${k}: ${r[k]} ms" style="width:${100*r[k]/tot}%;background:${C[k]}"></span>`).join("");
  return `<tr><td>${r.id}</td><td>${esc(r.created_at.slice(11,19))}</td><td>${esc(r.app||"")} · ${esc(r.style||"")}</td><td class="${r.status=="pasted"?"ok":"bad"}">${esc(r.status)}${r.error?"<br>"+esc(r.error):""}</td><td>${r.total_ms??""}</td><td><div class="bar">${bar}</div></td><td>${esc(r.asr_model||"")}${r.asr_retried?" (retry)":""}${r.chunks?` · ${r.chunks} chunks`:""}</td><td>${esc(r.llm_status||"")}${r.llm_reason?": "+esc(r.llm_reason):""}</td><td>${esc(r.guard_dropped||"")}</td><td>${r.edit_rate==null?"":(100*r.edit_rate).toFixed(0)+"%"}${r.learned?"<br>"+esc(r.learned):""}</td></tr>`}).join("");
 const e=await j("/api/edit_rate");
 document.getElementById("edit").innerHTML="<tr><th>clean-up</th><th>mean Edit Rate</th><th>n</th></tr>"+Object.entries(e).map(([k,v])=>`<tr><td>${esc(k)}</td><td>${(100*v.edit_rate).toFixed(1)}%</td><td>${v.n}</td></tr>`).join("");
 const w=await j("/api/words");
 document.getElementById("words").innerHTML="<tr><th>term</th><th>source</th><th>fixes</th></tr>"+w.map(r=>`<tr><td>${r.starred?"★ ":""}${esc(r.term)}</td><td>${esc(r.source)}</td><td>${r.uses}</td></tr>`).join("");
 const h=await j("/api/history");
 document.getElementById("history").innerHTML=h.length?"<tr><th>#</th><th>when</th><th>app</th><th>text</th></tr>"+h.map(r=>`<tr><td>${r.id}</td><td>${esc(r.created_at.slice(0,19))}</td><td>${esc(r.app||"")}</td><td>${esc(r.text)}</td></tr>`).join(""):"<tr><td>No stored text. Set store_text = true to keep history.</td></tr>";
}
load();setInterval(load,3000);
</script></body></html>"""

LOCAL_HOSTS = {"127.0.0.1", "localhost", "[::1]"}


def make_handler(store: Store):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_a):  # quiet
            pass

        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):  # noqa: N802
            host = (self.headers.get("Host") or "").rsplit(":", 1)[0]
            if host not in LOCAL_HOSTS:
                return self._send(403, b"forbidden", "text/plain")
            url = urlparse(self.path)
            q = parse_qs(url.query)
            if url.path == "/":
                return self._send(200, PAGE.encode(), "text/html; charset=utf-8")
            data = {
                "/api/dictations": lambda: [{k: r[k] for k in r.keys() if k != "text"} for r in store.recent(min(500, int(q.get("limit", ["50"])[0])))],
                "/api/summary": lambda: store.latency_summary(),
                "/api/edit_rate": lambda: store.edit_rate_summary(),
                "/api/words": lambda: [dict(r) for r in store.words()],
                "/api/history": lambda: [dict(r) for r in store.history(100)],
                "/api/stages": lambda: STAGES,
            }.get(url.path)
            if data is None:
                return self._send(404, b"not found", "text/plain")
            return self._send(200, json.dumps(data()).encode(), "application/json")

    return Handler


def serve(store: Store, port: int = 8765, background: bool = False) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(store))
    if background:
        threading.Thread(target=server.serve_forever, daemon=True, name="debug-panel").start()
    else:
        server.serve_forever()
    return server

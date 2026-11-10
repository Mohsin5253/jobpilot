// Fills the application form on this page when you press "Fill this application" in the popup.
// It types into fields, attaches your tailored resume and highlights what it changed. It never submits:
// when YOU submit, it tells JobPilot so the job moves to Applied.
(() => {
  const ask = (msg) => new Promise((resolve) => chrome.runtime.sendMessage(msg, resolve));
  let matchId = null;

  function labelFor(el) {
    if (el.id) {
      const l = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
      if (l) return l.innerText;
    }
    const wrap = el.closest("label, .field, .application-question, [class*='_fieldEntry'], li, .form-group, div");
    return (el.getAttribute("aria-label") || wrap?.querySelector("label, .application-label, legend")?.innerText || el.placeholder || "").trim();
  }

  function scan() {
    const els = [...document.querySelectorAll("input, textarea, select")].filter((el) => !el.disabled && el.offsetParent !== null || el.type === "file");
    return els.map((el, i) => {
      if (!el.dataset.jpId) el.dataset.jpId = `jp-${i}`;
      return {
        id: el.dataset.jpId,
        name: el.name || "",
        label: labelFor(el),
        type: (el.type || "").toLowerCase(),
        tag: el.tagName.toLowerCase(),
        autocomplete: el.getAttribute("autocomplete") || "",
        el,
      };
    });
  }

  // React-controlled inputs (Ashby, new Greenhouse) need the native setter, then input/change events.
  function setValue(el, value) {
    const proto = el.tagName === "TEXTAREA" ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(proto, "value").set.call(el, value);
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
    el.style.outline = "2px solid #D6B77A";
    el.style.outlineOffset = "2px";
  }

  async function attachResume(fields, path) {
    const input = JobPilotFields.resumeInput(fields)?.el;
    if (!input || !path) return false;
    const r = await ask({ type: "resume", path });
    if (!r?.ok) return false;
    const bytes = Uint8Array.from(atob(r.data.base64), (c) => c.charCodeAt(0));
    const dt = new DataTransfer();
    dt.items.add(new File([bytes], r.data.name, { type: "application/pdf" }));
    input.files = dt.files;
    input.dispatchEvent(new Event("change", { bubbles: true }));
    return true;
  }

  async function fill() {
    const r = await ask({ type: "autofill", url: location.href });
    if (!r?.ok) return { ok: false, error: r?.error || "Couldn't reach JobPilot" };
    const data = r.data;
    const fields = scan();
    const plan = JobPilotFields.planFill(fields, data);
    const byId = Object.fromEntries(fields.map((f) => [f.id, f.el]));
    for (const p of plan) {
      const el = byId[p.id];
      if (el && !el.value) setValue(el, p.value); // never overwrite what you typed
    }
    const resume = data.matched ? await attachResume(fields, data.resume_path) : false;
    matchId = data.matched ? data.match_id : null;
    return { ok: true, filled: plan.length, resume, matched: data.matched, job: data.job || null };
  }

  // Applied is recorded only after YOUR submit.
  document.addEventListener(
    "submit",
    () => {
      if (matchId) ask({ type: "applied", matchId });
    },
    true,
  );

  chrome.runtime.onMessage.addListener((msg, _sender, reply) => {
    if (msg?.type !== "fill") return false;
    fill().then(reply);
    return true;
  });
})();

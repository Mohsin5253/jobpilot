// Talks to the JobPilot API for the popup and the content script. API calls run here (the extension's own
// origin, with a personal token), never from the job site's page, so the site never sees your token.

async function settings() {
  const { apiUrl = "http://localhost:8000", token = "" } = await chrome.storage.local.get(["apiUrl", "token"]);
  return { apiUrl: apiUrl.replace(/\/$/, ""), token };
}

async function call(path, init = {}) {
  const { apiUrl, token } = await settings();
  if (!token) throw new Error("Add your JobPilot token in the extension popup first.");
  const res = await fetch(`${apiUrl}${path}`, { ...init, headers: { authorization: `Bearer ${token}`, "content-type": "application/json", ...(init.headers || {}) } });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail || detail;
    } catch {}
    throw new Error(typeof detail === "string" ? detail : "Request failed");
  }
  return res;
}

function toBase64(buffer) {
  let binary = "";
  const bytes = new Uint8Array(buffer);
  for (let i = 0; i < bytes.length; i += 0x8000) binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(binary);
}

const handlers = {
  async autofill({ url }) {
    return (await call(`/api/extension/autofill?url=${encodeURIComponent(url)}`)).json();
  },
  async resume({ path }) {
    const res = await call(path);
    const name = (res.headers.get("content-disposition") || "").match(/filename="([^"]+)"/)?.[1] || "resume.pdf";
    return { name, base64: toBase64(await res.arrayBuffer()) };
  },
  async applied({ matchId }) {
    return (await call("/api/extension/applied", { method: "POST", body: JSON.stringify({ match_id: matchId }) })).json();
  },
};

chrome.runtime.onMessage.addListener((msg, _sender, reply) => {
  const handler = handlers[msg?.type];
  if (!handler) return false;
  handler(msg)
    .then((data) => reply({ ok: true, data }))
    .catch((err) => reply({ ok: false, error: err.message }));
  return true; // async reply
});

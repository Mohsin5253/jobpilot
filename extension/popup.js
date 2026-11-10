const $ = (id) => document.getElementById(id);
const status = (html) => ($("status").innerHTML = html);
const ATS = /^https:\/\/(boards\.greenhouse\.io|job-boards\.greenhouse\.io|jobs\.lever\.co|jobs\.ashbyhq\.com)\//;

async function showSettings(show) {
  $("settings").classList.toggle("hidden", !show);
  $("main").classList.toggle("hidden", show);
  if (show) {
    const { apiUrl = "http://localhost:8000", token = "" } = await chrome.storage.local.get(["apiUrl", "token"]);
    $("api").value = apiUrl;
    $("token").value = token;
  }
}

$("edit").addEventListener("click", () => showSettings(true));

$("settings").addEventListener("submit", async (e) => {
  e.preventDefault();
  const apiUrl = $("api").value.trim().replace(/\/$/, "");
  const token = $("token").value.trim();
  try {
    const origin = new URL(apiUrl).origin;
    // Ask once for permission to reach your own API address (nothing else).
    const granted = await chrome.permissions.request({ origins: [`${origin}/*`] });
    if (!granted) throw new Error("Permission to reach the API was declined");
  } catch (err) {
    alert(err.message || "Enter a full address, like https://api.yourdomain.com");
    return;
  }
  await chrome.storage.local.set({ apiUrl, token });
  showSettings(false);
  init();
});

$("fill").addEventListener("click", async () => {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab || !ATS.test(tab.url || "")) return status("Open a Greenhouse, Lever or Ashby application page first.");
  status("Filling…");
  chrome.tabs.sendMessage(tab.id, { type: "fill" }, (r) => {
    if (chrome.runtime.lastError || !r) return status("Reload the page, then try again.");
    if (!r.ok) return status(`<b>Couldn’t fill.</b> ${r.error}`);
    const job = r.job ? `<b>${r.job.title}</b> at ${r.job.company} · ${r.job.score} fit<br>` : "Not a JobPilot match: your basic details only.<br>";
    status(`${job}Filled ${r.filled} field(s)${r.resume ? " and attached your tailored resume" : ""}. Check everything, then submit.`);
  });
});

async function init() {
  const { token } = await chrome.storage.local.get(["token"]);
  if (!token) return showSettings(true);
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (tab && ATS.test(tab.url || "")) status("Ready. Press <b>Fill this application</b>.");
}

init();

/**
 * Wakes the API when it's asleep. Render's free tier stops the API after 15 minutes without traffic, and requests
 * proxied from this site (the /api rewrite) are answered with 502 instead of waking it. A direct server-side request
 * does wake it (about 45 seconds), so the client calls this once when it sees a 502, then retries.
 */
export const dynamic = "force-dynamic";
export const maxDuration = 60;

const API_URL = (process.env.API_URL?.trim() || "http://localhost:8000").replace(/\/+$/, "").replace(/\/api$/, "");

export async function GET() {
  const started = Date.now();
  try {
    const res = await fetch(`${API_URL}/health`, { cache: "no-store", signal: AbortSignal.timeout(55_000) });
    return Response.json({ ok: res.ok, ms: Date.now() - started }, { status: res.ok ? 200 : 503, headers: { "cache-control": "no-store" } });
  } catch {
    return Response.json({ ok: false, ms: Date.now() - started }, { status: 503, headers: { "cache-control": "no-store" } });
  }
}

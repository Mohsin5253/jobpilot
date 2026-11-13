import { NextResponse, type NextRequest } from "next/server";

// Public pages: the landing page, trust and legal pages and the sign-in flows. Everything else needs a session.
const PUBLIC = ["/login", "/register", "/forgot-password", "/reset-password", "/privacy", "/terms", "/trust", "/transparency", "/scam-check", "/scam-card", "/campus-pricing", "/p/", "/wake"];
const AUTH_ONLY = ["/login", "/register"];

/** The Campus portal (/campus/**) is for approved college staff only. Every page asks the API (which checks the staff
 * session, the membership status and the account version) before rendering; students and everyone else go back to
 * the student app. The API and row-level security enforce the same rule again for every request. */
async function staffOnly(req: NextRequest): Promise<NextResponse | null> {
  const { pathname } = req.nextUrl;
  if (pathname !== "/campus" && !pathname.startsWith("/campus/")) return null;
  const to = (path: string) => {
    const url = req.nextUrl.clone();
    url.pathname = path;
    url.search = path === "/staff-access" ? `?next=${encodeURIComponent(pathname)}` : "?staff_only=1";
    return NextResponse.redirect(url);
  };
  if (!req.cookies.has("jp_staff")) return to("/staff-access");
  try {
    const r = await fetch(new URL("/api/campus/staff/access", req.url), { headers: { cookie: req.headers.get("cookie") ?? "" }, cache: "no-store" });
    if (r.ok) return NextResponse.next();
    const detail = r.status === 403 ? String(((await r.json().catch(() => ({}))) as { detail?: string }).detail ?? "") : "";
    return to(r.status === 401 || detail.startsWith("staff_session_required") ? "/staff-access" : "/campus-profile");
  } catch {
    return to("/staff-access");
  }
}

export async function middleware(req: NextRequest) {
  const { pathname } = req.nextUrl;
  const authed = req.cookies.has("jp_session");
  const isPublic = pathname === "/" || PUBLIC.some((p) => pathname.startsWith(p));
  if (!authed && !isPublic) {
    const url = req.nextUrl.clone();
    url.pathname = "/login";
    url.searchParams.set("next", pathname);
    return NextResponse.redirect(url);
  }
  // Signed in: the landing page and sign-in forms go straight to the dashboard.
  if (authed && (pathname === "/" || AUTH_ONLY.some((p) => pathname.startsWith(p)))) return NextResponse.redirect(new URL("/dashboard", req.url));
  if (authed && pathname === "/college") return NextResponse.redirect(new URL("/campus", req.url));  // the v1 staff page moved
  return (await staffOnly(req)) ?? NextResponse.next();
}

export const config = { matcher: ["/((?!api|_next|favicon|icon|.*\\..*).*)"] };

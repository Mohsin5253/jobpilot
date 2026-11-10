import { NextResponse, type NextRequest } from "next/server";

// Public pages: the landing page, legal pages and the sign-in flows. Everything else needs a session.
const PUBLIC = ["/login", "/register", "/forgot-password", "/reset-password", "/privacy", "/terms", "/p/"];
const AUTH_ONLY = ["/login", "/register"];

export function middleware(req: NextRequest) {
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
  return NextResponse.next();
}

export const config = { matcher: ["/((?!api|_next|favicon|icon|.*\\..*).*)"] };

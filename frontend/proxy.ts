import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

// Optimistic check only: if there is clearly no session, skip rendering the
// dashboard and go to /login. The real authorization happens in FastAPI on
// every API call (a cookie here proves nothing by itself).
// `csp_csrf` lives as long as the refresh token and is readable at path "/".
const SESSION_HINT_COOKIE = "csp_csrf";

export function proxy(request: NextRequest) {
  const hasSession = request.cookies.has(SESSION_HINT_COOKIE);
  const { pathname } = request.nextUrl;

  if (!hasSession && pathname !== "/login") {
    const url = new URL("/login", request.url);
    if (pathname !== "/") url.searchParams.set("next", pathname);
    return NextResponse.redirect(url);
  }
  if (hasSession && pathname === "/login") {
    return NextResponse.redirect(new URL("/dashboard", request.url));
  }
  return NextResponse.next();
}

export const config = {
  // Run on pages only, not on API calls, Next.js internals or static files.
  matcher: ["/((?!api|_next/static|_next/image|favicon.ico|.*\\..*).*)"],
};

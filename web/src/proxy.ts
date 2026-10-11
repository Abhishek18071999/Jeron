// Every page, server action and route handler needs a login (src/lib/auth.ts), except
// the login page itself and static files.
import { type NextRequest, NextResponse } from "next/server";

import { SESSION_COOKIE, loginConfig, validSession } from "@/lib/auth";

export function proxy(request: NextRequest) {
  const config = loginConfig();
  if (config.mode === "off") return NextResponse.next();
  const { pathname, search } = request.nextUrl;
  if (pathname === "/login") return NextResponse.next();
  if (config.mode === "on" && validSession(request.cookies.get(SESSION_COOKIE)?.value, config)) {
    return NextResponse.next();
  }
  if (pathname.startsWith("/api/")) {
    return NextResponse.json({ error: "Log in first" }, { status: 401 });
  }
  const url = request.nextUrl.clone();
  url.pathname = "/login";
  url.search = pathname === "/" ? "" : `?next=${encodeURIComponent(pathname + search)}`;
  return NextResponse.redirect(url);
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|icons/|favicon.ico|manifest.webmanifest).*)"],
};

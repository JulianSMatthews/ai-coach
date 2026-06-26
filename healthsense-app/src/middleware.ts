import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

const PUBLIC_PATHS = [
  "/login",
  "/reset-password",
  "/setup-security",
  "/ig/start",
  "/privacy",
  "/terms",
  "/support",
  "/delete-account",
  "/coachsense.html",
  "/coachsense-icon.svg",
  "/coachsense-logo.svg",
  "/healthsense-mark.svg",
];

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;
  if (
    pathname.startsWith("/_next") ||
    pathname.startsWith("/api") ||
    pathname.startsWith("/favicon") ||
    pathname.startsWith("/assets") ||
    pathname.startsWith("/reports")
  ) {
    return NextResponse.next();
  }
  if (pathname.startsWith("/assessment/lead/chat")) {
    return NextResponse.next();
  }
  if (PUBLIC_PATHS.includes(pathname)) {
    return NextResponse.next();
  }
  const session = request.cookies.get("hs_session")?.value;
  if (!session) {
    const url = request.nextUrl.clone();
    const nextPath = `${pathname}${request.nextUrl.search || ""}`;
    if (nextPath && nextPath.startsWith("/") && !nextPath.startsWith("//")) {
      url.searchParams.set("next", nextPath);
    }
    url.pathname = "/login";
    return NextResponse.redirect(url);
  }
  const pathParts = pathname.split("/").filter(Boolean);
  const isDashboard = pathParts[0] === "dashboard";
  if (isDashboard) {
    const url = request.nextUrl.clone();
    url.pathname = "/";
    return NextResponse.redirect(url);
  }
  return NextResponse.next();
}

export const config = {
  matcher: ["/:path*"],
};

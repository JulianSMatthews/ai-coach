import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

const PUBLIC_PATHS = ["/login", "/setup-security"];

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;
  if (
    pathname.startsWith("/_next") ||
    pathname.startsWith("/api") ||
    pathname.startsWith("/favicon") ||
    pathname.startsWith("/assets")
  ) {
    return NextResponse.next();
  }
  if (PUBLIC_PATHS.includes(pathname)) {
    return NextResponse.next();
  }
  const session = request.cookies.get("hs_session")?.value;
  if (!session) {
    const url = request.nextUrl.clone();
    url.pathname = "/login";
    return NextResponse.redirect(url);
  }
  const pathParts = pathname.split("/").filter(Boolean);
  const isDashboard = pathParts[0] === "dashboard";
  if (isDashboard) {
    const rawUserId =
      pathParts[1] ||
      request.cookies.get("hs_user_id")?.value ||
      process.env.NEXT_PUBLIC_DEFAULT_USER_ID ||
      "1";
    const userId = String(rawUserId).replace(/[^0-9]/g, "") || "1";
    const url = request.nextUrl.clone();
    url.pathname = `/progress/${userId}`;
    return NextResponse.redirect(url);
  }
  return NextResponse.next();
}

export const config = {
  matcher: ["/:path*"],
};

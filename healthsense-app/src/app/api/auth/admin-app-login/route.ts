import { NextResponse } from "next/server";

const DEFAULT_MAX_AGE_SECONDS = 60 * 30;

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const sessionToken = (searchParams.get("session_token") || "").trim();
  const userIdRaw = (searchParams.get("user_id") || "").trim();
  const nextRaw = (searchParams.get("next") || "").trim();

  if (!sessionToken) {
    return NextResponse.redirect(new URL("/login", request.url));
  }

  const userId = String(Number(userIdRaw || "0") || "");
  const nextPath =
    nextRaw && nextRaw.startsWith("/") && !nextRaw.startsWith("//")
      ? nextRaw
      : userId
        ? `/progress/${userId}`
        : "/login";

  const response = NextResponse.redirect(new URL(nextPath, request.url));
  response.cookies.set("hs_session", sessionToken, {
    httpOnly: true,
    sameSite: "lax",
    path: "/",
    maxAge: DEFAULT_MAX_AGE_SECONDS,
    secure: process.env.NODE_ENV === "production",
  });
  if (userId) {
    response.cookies.set("hs_user_id", userId, {
      httpOnly: false,
      sameSite: "lax",
      path: "/",
      maxAge: DEFAULT_MAX_AGE_SECONDS,
      secure: process.env.NODE_ENV === "production",
    });
  }
  return response;
}

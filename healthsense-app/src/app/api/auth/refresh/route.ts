import { NextResponse } from "next/server";

export async function POST(request: Request) {
  const base = process.env.API_BASE_URL;
  if (!base) {
    return NextResponse.json({ error: "API_BASE_URL is not set" }, { status: 500 });
  }
  const body = await request.json().catch(() => ({}));
  const token = body?.token;
  if (!token) {
    return NextResponse.json({ error: "token required" }, { status: 400 });
  }
  const res = await fetch(`${base.replace(/\/+$/, "")}/api/v1/auth/me`, {
    headers: { "X-Session-Token": token },
  });
  if (!res.ok) {
    return NextResponse.json({ error: "invalid session" }, { status: 401 });
  }
  const data = await res.json();
  const userId = data?.user?.id;
  const response = NextResponse.json({ ok: true, user_id: userId });
  const maxAge = 60 * 60 * 24 * 30;
  response.cookies.set("hs_session", token, {
    httpOnly: true,
    sameSite: "lax",
    path: "/",
    maxAge,
    secure: process.env.NODE_ENV === "production",
  });
  if (userId) {
    response.cookies.set("hs_user_id", String(userId), {
      httpOnly: false,
      sameSite: "lax",
      path: "/",
      maxAge,
      secure: process.env.NODE_ENV === "production",
    });
  }
  return response;
}

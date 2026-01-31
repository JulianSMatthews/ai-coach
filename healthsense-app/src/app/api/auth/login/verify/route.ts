import { NextResponse } from "next/server";

export async function POST(request: Request) {
  const base = process.env.API_BASE_URL;
  if (!base) {
    return NextResponse.json({ error: "API_BASE_URL is not set" }, { status: 500 });
  }
  const body = await request.json().catch(() => ({}));
  const res = await fetch(`${base.replace(/\/+$/, "")}/api/v1/auth/login/verify`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const text = await res.text();
  if (!res.ok) {
    return NextResponse.json({ error: text || "Failed to verify OTP" }, { status: res.status });
  }
  const data = JSON.parse(text);
  const response = NextResponse.json(data);
  const token = data.session_token;
  const userId = data.user_id;
  const rememberDays = Number(data.remember_days || 7);
  const maxAge = rememberDays * 24 * 60 * 60;
  if (token) {
    response.cookies.set("hs_session", token, {
      httpOnly: true,
      sameSite: "lax",
      path: "/",
      maxAge,
      secure: process.env.NODE_ENV === "production",
    });
  }
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

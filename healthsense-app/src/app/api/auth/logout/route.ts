import { NextResponse } from "next/server";

export async function POST(request: Request) {
  const base = process.env.API_BASE_URL;
  if (!base) {
    return NextResponse.json({ error: "API_BASE_URL is not set" }, { status: 500 });
  }
  const cookieHeader = request.headers.get("cookie") || "";
  const match = cookieHeader.match(/(?:^|; )hs_session=([^;]+)/);
  const session = match ? match[1] : null;
  if (session) {
    await fetch(`${base.replace(/\/+$/, "")}/api/v1/auth/logout`, {
      method: "POST",
      headers: { "X-Session-Token": session },
    }).catch(() => null);
  }
  const response = NextResponse.json({ ok: true });
  response.cookies.set("hs_session", "", { path: "/", maxAge: 0 });
  response.cookies.set("hs_user_id", "", { path: "/", maxAge: 0 });
  return response;
}

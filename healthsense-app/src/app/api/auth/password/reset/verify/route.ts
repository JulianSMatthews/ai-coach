import { NextResponse } from "next/server";

function extractUpstreamMessage(text: string): string {
  const raw = (text || "").trim();
  if (!raw) return "";
  try {
    const parsed = JSON.parse(raw) as unknown;
    if (typeof parsed === "string") return parsed;
    if (parsed && typeof parsed === "object") {
      const obj = parsed as Record<string, unknown>;
      const direct = obj.detail ?? obj.error ?? obj.message;
      if (typeof direct === "string") return direct;
    }
  } catch {}
  return raw;
}

export async function POST(request: Request) {
  const base = process.env.API_BASE_URL;
  if (!base) {
    return NextResponse.json({ error: "API_BASE_URL is not set" }, { status: 500 });
  }
  const body = await request.json().catch(() => ({}));
  let res: Response;
  try {
    res = await fetch(`${base.replace(/\/+$/, "")}/api/v1/auth/password/reset/verify`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch (error) {
    const msg = error instanceof Error ? error.message : String(error);
    return NextResponse.json({ error: `Proxy request failed: ${msg}` }, { status: 502 });
  }
  const text = await res.text().catch(() => "");
  if (!res.ok) {
    return NextResponse.json({ error: extractUpstreamMessage(text) || "Failed to reset password" }, { status: res.status });
  }
  if (!text.trim()) {
    return NextResponse.json({ error: "Upstream returned invalid response." }, { status: 502 });
  }
  let data: Record<string, unknown>;
  try {
    data = JSON.parse(text) as Record<string, unknown>;
  } catch {
    return NextResponse.json({ error: "Upstream returned invalid response." }, { status: 502 });
  }
  const response = NextResponse.json(data);
  const token = typeof data.session_token === "string" ? data.session_token : "";
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

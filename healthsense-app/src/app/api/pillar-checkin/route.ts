import { NextRequest, NextResponse } from "next/server";

async function proxy(request: NextRequest) {
  const session = request.cookies.get("hs_session")?.value;
  if (!session) return NextResponse.json({ error: "Please sign in to check in." }, { status: 401 });
  const body = request.method === "POST" ? await request.json().catch(() => null) : null;
  const userId = String(body?.userId || request.nextUrl.searchParams.get("userId") || request.cookies.get("hs_user_id")?.value || "");
  if (!/^\d+$/.test(userId)) return NextResponse.json({ error: "A valid userId is required." }, { status: 400 });
  const base = process.env.API_BASE_URL?.replace(/\/+$/, "");
  if (!base) return NextResponse.json({ error: "Check-in service is unavailable." }, { status: 503 });
  try {
    const suffix = request.method === "POST" && body?.action === "voice-session" ? "/voice-session" : "";
    const res = await fetch(`${base}/api/v1/users/${userId}/pillar-checkin${suffix}`, {
      method: request.method,
      headers: { "X-Session-Token": session, "Content-Type": "application/json" },
      body: request.method === "POST" ? JSON.stringify({ text: body?.text, request_id: body?.request_id }) : undefined,
      cache: "no-store",
    });
    const data = await res.json();
    if (!res.ok) return NextResponse.json({ error: typeof data.detail === "string" ? data.detail : "Could not complete the check-in request." }, { status: res.status });
    return NextResponse.json(data, { headers: { "Cache-Control": "no-store" } });
  } catch {
    return NextResponse.json({ error: "Could not reach your coach. Please try again." }, { status: 502 });
  }
}

export const GET = proxy;
export const POST = proxy;

import { NextResponse } from "next/server";

export async function GET(request: Request) {
  const cookieHeader = request.headers.get("cookie") || "";
  const cookieValue = (name: string) => cookieHeader.match(new RegExp(`(?:^|;\\s*)${name}=([^;]+)`))?.[1] || "";
  const session = cookieValue("hs_session");
  if (!session) return NextResponse.json({ error: "Sign in to view your progress." }, { status: 401 });
  const userId = (new URL(request.url).searchParams.get("userId") || cookieValue("hs_user_id")).trim();
  if (!/^[1-9]\d*$/.test(userId)) return NextResponse.json({ error: "Invalid progress request." }, { status: 400 });
  const base = process.env.API_BASE_URL?.replace(/\/+$/, "");
  if (!base) return NextResponse.json({ error: "Progress is unavailable. Please try again shortly." }, { status: 503 });
  try {
    const response = await fetch(`${base}/api/v1/users/${encodeURIComponent(userId)}/pillar-progress`, {
      headers: { "X-Session-Token": session }, cache: "no-store", signal: request.signal,
    });
    if (!response.ok) return NextResponse.json({ error: "Could not load your progress. Please try again." }, { status: response.status });
    return NextResponse.json(await response.json(), { headers: { "Cache-Control": "private, no-store" } });
  } catch {
    return NextResponse.json({ error: "Could not load your progress. Please try again." }, { status: 502 });
  }
}

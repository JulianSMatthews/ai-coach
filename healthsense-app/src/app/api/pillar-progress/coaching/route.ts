import { NextResponse } from "next/server";

const PILLARS = new Set(["reflection", "purpose", "resilience", "recovery", "nutrition", "training"]);

export async function POST(request: Request) {
  const cookieHeader = request.headers.get("cookie") || "";
  const cookieValue = (name: string) => cookieHeader.match(new RegExp(`(?:^|;\\s*)${name}=([^;]+)`))?.[1] || "";
  const session = cookieValue("hs_session");
  if (!session) return NextResponse.json({ error: "Sign in to view your guidance." }, { status: 401 });
  const body = await request.json().catch(() => null);
  const userId = String(body?.userId || cookieValue("hs_user_id")).trim();
  const pillarKey = String(body?.pillarKey || "").trim();
  const conceptKey = String(body?.conceptKey || "").trim();
  if (!/^[1-9]\d*$/.test(userId) || !PILLARS.has(pillarKey) || !/^[a-z][a-z0-9_]{0,79}$/.test(conceptKey)) {
    return NextResponse.json({ error: "Choose a valid concept to get guidance." }, { status: 400 });
  }
  const base = process.env.API_BASE_URL?.replace(/\/+$/, "");
  if (!base) return NextResponse.json({ error: "Guidance is unavailable. Please try again shortly." }, { status: 503 });
  try {
    const response = await fetch(`${base}/api/v1/users/${encodeURIComponent(userId)}/pillar-progress/coaching`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Session-Token": session },
      body: JSON.stringify({ pillar_key: pillarKey, concept_key: conceptKey }),
      cache: "no-store", signal: request.signal,
    });
    if (!response.ok) {
      const error = response.status === 503
        ? "AI guidance is unavailable right now. Your progress is still available; please try again later."
        : "Could not load guidance for this concept. Please try again.";
      return NextResponse.json({ error }, { status: response.status });
    }
    return NextResponse.json(await response.json(), { headers: { "Cache-Control": "private, no-store" } });
  } catch {
    return NextResponse.json({ error: "Could not load guidance for this concept. Please try again." }, { status: 502 });
  }
}

import { NextResponse } from "next/server";

const PILLARS = new Set(["reflection", "purpose", "resilience", "recovery", "nutrition", "training"]);

function cookieValue(header: string, name: string): string {
  return header.match(new RegExp(`(?:^|;\\s*)${name}=([^;]+)`))?.[1] || "";
}

export async function GET(request: Request) {
  const cookieHeader = request.headers.get("cookie") || "";
  const session = cookieValue(cookieHeader, "hs_session");
  if (!session) {
    return NextResponse.json({ error: "Sign in to view previous insights." }, { status: 401 });
  }

  const url = new URL(request.url);
  const userId = (url.searchParams.get("userId") || cookieValue(cookieHeader, "hs_user_id")).trim();
  const pillarKey = (url.searchParams.get("pillarKey") || "").trim().toLowerCase();
  const before = (url.searchParams.get("before") || "").trim();
  const limit = url.searchParams.get("limit") || "10";
  if (
    !/^[1-9]\d*$/.test(userId) ||
    !PILLARS.has(pillarKey) ||
    (before && !/^\d{4}-\d{2}-\d{2}$/.test(before)) ||
    !/^\d+$/.test(limit) || Number(limit) < 1 || Number(limit) > 30
  ) {
    return NextResponse.json({ error: "Invalid insight history request." }, { status: 400 });
  }

  const base = process.env.API_BASE_URL?.replace(/\/+$/, "");
  if (!base) {
    return NextResponse.json({ error: "Insight history is unavailable." }, { status: 503 });
  }

  try {
    const params = new URLSearchParams({ limit });
    if (before) params.set("before", before);
    const upstream = `${base}/api/v1/users/${encodeURIComponent(userId)}/pillar-tracker/${encodeURIComponent(pillarKey)}/insights?${params}`;
    const response = await fetch(upstream, {
      headers: { "X-Session-Token": session },
      cache: "no-store",
      signal: request.signal,
    });
    if (!response.ok) {
      return NextResponse.json(
        { error: "Could not load previous insights." },
        { status: response.status },
      );
    }
    return NextResponse.json(await response.json());
  } catch {
    return NextResponse.json({ error: "Could not load previous insights." }, { status: 502 });
  }
}

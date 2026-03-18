import { NextResponse } from "next/server";

function getBaseUrl() {
  const base = process.env.API_BASE_URL;
  if (!base) {
    throw new Error("API_BASE_URL is not set");
  }
  return base.replace(/\/+$/, "");
}

function getAdminHeaders() {
  const token = process.env.ADMIN_API_TOKEN;
  const adminUserId = process.env.ADMIN_USER_ID;
  if (!token || !adminUserId) {
    throw new Error("ADMIN_API_TOKEN or ADMIN_USER_ID is not set");
  }
  return {
    "X-Admin-Token": token,
    "X-Admin-User-Id": adminUserId,
  };
}

function getCookieValue(cookieHeader: string, key: string): string | null {
  const match = cookieHeader.match(new RegExp(`(?:^|; )${key}=([^;]+)`));
  return match ? match[1] : null;
}

function buildHeaders(cookieHeader: string, includeContentType = false): Record<string, string> {
  const session = getCookieValue(cookieHeader, "hs_session");
  const headers: Record<string, string> = {};
  if (includeContentType) {
    headers["Content-Type"] = "application/json";
  }
  if (session) {
    headers["X-Session-Token"] = session;
  } else {
    Object.assign(headers, getAdminHeaders());
  }
  return headers;
}

export async function GET(
  request: Request,
  context: { params: Promise<{ pillar: string }> },
) {
  try {
    const { pillar } = await context.params;
    const url = new URL(request.url);
    const cookieHeader = request.headers.get("cookie") || "";
    const userId = String(url.searchParams.get("userId") || getCookieValue(cookieHeader, "hs_user_id") || "").trim();
    const anchorDate = String(url.searchParams.get("anchorDate") || "").trim();
    if (!userId) {
      return NextResponse.json({ error: "userId is required" }, { status: 400 });
    }
    const params = new URLSearchParams();
    if (anchorDate) {
      params.set("anchor_date", anchorDate);
    }
    const base = getBaseUrl();
    const upstream = `${base}/api/v1/users/${encodeURIComponent(userId)}/pillar-tracker/${encodeURIComponent(pillar)}${params.toString() ? `?${params.toString()}` : ""}`;
    const res = await fetch(upstream, {
      method: "GET",
      headers: buildHeaders(cookieHeader),
      cache: "no-store",
    });
    const text = await res.text().catch(() => "");
    if (!res.ok) {
      return NextResponse.json({ error: text || "Failed to load pillar tracker detail" }, { status: res.status });
    }
    return NextResponse.json(text ? JSON.parse(text) : {});
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}

export async function POST(
  request: Request,
  context: { params: Promise<{ pillar: string }> },
) {
  try {
    const { pillar } = await context.params;
    const body = (await request.json().catch(() => ({}))) as Record<string, unknown>;
    const cookieHeader = request.headers.get("cookie") || "";
    const userId = String(body.userId || getCookieValue(cookieHeader, "hs_user_id") || "").trim();
    if (!userId) {
      return NextResponse.json({ error: "userId is required" }, { status: 400 });
    }
    const payload = {
      score_date: body.score_date ?? undefined,
      entries: Array.isArray(body.entries) ? body.entries : [],
    };
    const base = getBaseUrl();
    const upstream = `${base}/api/v1/users/${encodeURIComponent(userId)}/pillar-tracker/${encodeURIComponent(pillar)}`;
    const res = await fetch(upstream, {
      method: "POST",
      headers: buildHeaders(cookieHeader, true),
      body: JSON.stringify(payload),
      cache: "no-store",
    });
    const text = await res.text().catch(() => "");
    if (!res.ok) {
      return NextResponse.json({ error: text || "Failed to save pillar tracker" }, { status: res.status });
    }
    return NextResponse.json(text ? JSON.parse(text) : {});
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}

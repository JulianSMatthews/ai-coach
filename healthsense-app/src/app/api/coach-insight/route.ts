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

export async function GET(request: Request) {
  try {
    const url = new URL(request.url);
    const cookieHeader = request.headers.get("cookie") || "";
    const userId = String(url.searchParams.get("userId") || getCookieValue(cookieHeader, "hs_user_id") || "").trim();
    const anchorDate = String(url.searchParams.get("anchorDate") || "").trim();
    const conceptKey = String(url.searchParams.get("conceptKey") || "").trim();
    if (!userId) {
      return NextResponse.json({ error: "userId is required" }, { status: 400 });
    }
    const params = new URLSearchParams();
    if (anchorDate) {
      params.set("anchor_date", anchorDate);
    }
    if (conceptKey) {
      params.set("concept_key", conceptKey);
    }
    const base = getBaseUrl();
    const upstream = `${base}/api/v1/users/${encodeURIComponent(userId)}/coach-insight${params.toString() ? `?${params.toString()}` : ""}`;
    const session = getCookieValue(cookieHeader, "hs_session");
    const headers: Record<string, string> = {};
    if (session) {
      headers["X-Session-Token"] = session;
    } else {
      Object.assign(headers, getAdminHeaders());
    }
    const res = await fetch(upstream, {
      method: "GET",
      headers,
      cache: "no-store",
    });
    const text = await res.text().catch(() => "");
    if (!res.ok) {
      return NextResponse.json({ error: text || "Failed to load coach insight" }, { status: res.status });
    }
    return NextResponse.json(text ? JSON.parse(text) : {});
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}

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
    const force = String(url.searchParams.get("force") || "").trim();
    const conceptKey = String(url.searchParams.get("conceptKey") || "").trim();
    if (!userId) {
      return NextResponse.json({ error: "userId is required" }, { status: 400 });
    }
    const params = new URLSearchParams();
    if (force) {
      params.set("force", force);
    }
    if (conceptKey) {
      params.set("concept_key", conceptKey);
    }
    const base = getBaseUrl();
    const upstream = `${base}/api/v1/users/${encodeURIComponent(userId)}/daily-habits${params.toString() ? `?${params.toString()}` : ""}`;
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
      return NextResponse.json({ error: text || "Failed to load daily habits" }, { status: res.status });
    }
    return NextResponse.json(text ? JSON.parse(text) : {});
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}

export async function POST(request: Request) {
  try {
    const cookieHeader = request.headers.get("cookie") || "";
    const body = await request.json().catch(() => ({}));
    const userId = String(body?.userId || getCookieValue(cookieHeader, "hs_user_id") || "").trim();
    if (!userId) {
      return NextResponse.json({ error: "userId is required" }, { status: 400 });
    }
    const payload = {
      concept_key: String(body?.conceptKey || "").trim() || undefined,
      selected_option_ids: Array.isArray(body?.selectedOptionIds) ? body.selectedOptionIds : [],
    };
    const base = getBaseUrl();
    const upstream = `${base}/api/v1/users/${encodeURIComponent(userId)}/daily-habits`;
    const session = getCookieValue(cookieHeader, "hs_session");
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
    };
    if (session) {
      headers["X-Session-Token"] = session;
    } else {
      Object.assign(headers, getAdminHeaders());
    }
    const res = await fetch(upstream, {
      method: "POST",
      headers,
      body: JSON.stringify(payload),
      cache: "no-store",
    });
    const text = await res.text().catch(() => "");
    if (!res.ok) {
      return NextResponse.json({ error: text || "Failed to update daily habits" }, { status: res.status });
    }
    return NextResponse.json(text ? JSON.parse(text) : {});
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}

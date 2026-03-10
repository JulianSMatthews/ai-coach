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

function decodeCookieToken(value: string | null): string {
  if (!value) return "";
  try {
    return decodeURIComponent(value);
  } catch {
    return value;
  }
}

function isLeadGuestUserId(value: unknown): boolean {
  const token = String(value ?? "").trim().toLowerCase();
  return token === "lead" || token === "0" || token === "guest";
}

const LEAD_Q1_FALLBACK =
  "Q1/15 · Nutrition: In the last 7 days, how many portions of fruit and vegetables did you *eat on average per day*? For reference: 1 portion = 1 apple or banana, 1 fist-sized serving of vegetables, or 1 handful of salad or berries.";

export async function GET(request: Request) {
  try {
    const urlObj = new URL(request.url);
    const cookieHeader = request.headers.get("cookie") || "";
    const userId = urlObj.searchParams.get("userId") || getCookieValue(cookieHeader, "hs_user_id");
    const leadToken = getCookieValue(cookieHeader, "hs_lead_token");
    const leadMode = isLeadGuestUserId(userId) || (!userId && Boolean(leadToken));
    if (leadMode) {
      const firstQuestion = decodeCookieToken(getCookieValue(cookieHeader, "hs_lead_q1")) || LEAD_Q1_FALLBACK;
      return NextResponse.json({
        ok: true,
        has_active_session: false,
        identity_required: true,
        messages: [
          {
            id: 0,
            direction: "outbound",
            channel: "app",
            text: firstQuestion,
            created_at: new Date().toISOString(),
          },
        ],
      });
    }
    if (!userId) {
      return NextResponse.json({ error: "userId is required" }, { status: 400 });
    }

    const session = getCookieValue(cookieHeader, "hs_session");
    const headers: Record<string, string> = {};
    if (session) {
      headers["X-Session-Token"] = session;
    } else {
      Object.assign(headers, getAdminHeaders());
    }

    const base = getBaseUrl();
    const url = `${base}/api/v1/users/${encodeURIComponent(String(userId))}/assessment/chat/state`;
    const res = await fetch(url, {
      method: "GET",
      headers,
      cache: "no-store",
    });
    const text = await res.text().catch(() => "");
    if (!res.ok) {
      return NextResponse.json({ error: text || "Failed to load assessment chat state" }, { status: res.status });
    }
    if (!text) {
      return NextResponse.json({ ok: true });
    }
    try {
      return NextResponse.json(JSON.parse(text));
    } catch {
      return NextResponse.json({ error: "Upstream returned invalid response." }, { status: 502 });
    }
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}

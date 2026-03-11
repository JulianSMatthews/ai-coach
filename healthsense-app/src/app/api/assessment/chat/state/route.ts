import { NextResponse } from "next/server";
import { buildLeadFirstPrompt, LEAD_Q1_FALLBACK } from "../leadPrompt";

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

function resolveAssessmentUserId(rawUserId: unknown, cookieHeader: string, explicitLeadToken?: string | null): string | null {
  const requestedUserId = String(rawUserId ?? "").trim();
  const sessionUserId = String(getCookieValue(cookieHeader, "hs_user_id") || "").trim();
  const leadToken = explicitLeadToken || getCookieValue(cookieHeader, "hs_lead_token");
  if (requestedUserId && isLeadGuestUserId(requestedUserId)) {
    if (leadToken) return requestedUserId;
    return null;
  }
  if (requestedUserId) return requestedUserId;
  return sessionUserId || null;
}

export async function GET(request: Request) {
  try {
    const urlObj = new URL(request.url);
    const cookieHeader = request.headers.get("cookie") || "";
    const leadTokenParam = String(urlObj.searchParams.get("lt") || "").trim();
    const requestedUserId = urlObj.searchParams.get("userId") || getCookieValue(cookieHeader, "hs_user_id");
    const userId = resolveAssessmentUserId(requestedUserId, cookieHeader, leadTokenParam || null);
    const leadToken = leadTokenParam || getCookieValue(cookieHeader, "hs_lead_token");
    const leadMode = (isLeadGuestUserId(requestedUserId) || (!userId && Boolean(leadToken))) && !(userId && !isLeadGuestUserId(userId));
    if (leadMode) {
      if (!leadToken) {
        return NextResponse.json({ error: "Lead session expired. Please reopen the assessment link." }, { status: 401 });
      }
      const firstQuestion = decodeCookieToken(getCookieValue(cookieHeader, "hs_lead_q1")) || LEAD_Q1_FALLBACK;
      return NextResponse.json({
        ok: true,
        has_active_session: false,
        identity_required: true,
        current_prompt: buildLeadFirstPrompt(firstQuestion),
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

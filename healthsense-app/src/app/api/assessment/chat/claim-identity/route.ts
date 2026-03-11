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

function isLeadGuestUserId(value: unknown): boolean {
  const token = String(value ?? "").trim().toLowerCase();
  return token === "lead" || token === "0" || token === "guest";
}

function resolveAssessmentUserId(rawUserId: unknown, cookieHeader: string, explicitLeadToken?: string | null): string | null {
  const requestedUserId = String(rawUserId ?? "").trim();
  const sessionUserId = String(getCookieValue(cookieHeader, "hs_user_id") || "").trim();
  const leadToken = explicitLeadToken || getCookieValue(cookieHeader, "hs_lead_token");
  if (requestedUserId && isLeadGuestUserId(requestedUserId)) {
    if (sessionUserId && !isLeadGuestUserId(sessionUserId)) {
      return sessionUserId;
    }
    if (leadToken) return requestedUserId;
    return null;
  }
  if (requestedUserId) return requestedUserId;
  return sessionUserId || null;
}

export async function POST(request: Request) {
  try {
    const body = (await request.json().catch(() => ({}))) as Record<string, unknown>;
    const cookieHeader = request.headers.get("cookie") || "";
    const explicitLeadToken = String(body.lead_token || "").trim();
    const userId = resolveAssessmentUserId(
      body.userId ?? getCookieValue(cookieHeader, "hs_user_id"),
      cookieHeader,
      explicitLeadToken || null,
    );
    if (!userId) {
      return NextResponse.json({ error: "userId is required" }, { status: 400 });
    }

    const payload = {
      first_name: body.first_name ?? "",
      surname: body.surname ?? "",
      phone: body.phone ?? "",
      email: body.email ?? "",
      consent: body.consent ?? false,
    };

    const session = getCookieValue(cookieHeader, "hs_session");
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
    };
    if (session) {
      headers["X-Session-Token"] = session;
    } else {
      Object.assign(headers, getAdminHeaders());
    }

    const base = getBaseUrl();
    const url = `${base}/api/v1/users/${encodeURIComponent(String(userId))}/assessment/chat/claim-identity`;
    const res = await fetch(url, {
      method: "POST",
      headers,
      body: JSON.stringify(payload),
      cache: "no-store",
    });
    const text = await res.text().catch(() => "");
    if (!res.ok) {
      return NextResponse.json({ error: text || "Failed to claim identity" }, { status: res.status });
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

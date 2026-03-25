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
      password: body.password ?? "",
      preferred_channel: body.preferred_channel ?? "",
      marketing_opt_in: body.marketing_opt_in ?? undefined,
      create_app_session: body.create_app_session ?? undefined,
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
    let data: Record<string, unknown>;
    try {
      data = JSON.parse(text) as Record<string, unknown>;
    } catch {
      return NextResponse.json({ error: "Upstream returned invalid response." }, { status: 502 });
    }
    const response = NextResponse.json(data);
    const token = typeof data.session_token === "string" ? data.session_token : "";
    const responseUser = data.user && typeof data.user === "object" ? (data.user as Record<string, unknown>) : null;
    const userIdValue = responseUser?.id;
    const rememberDaysRaw = Number(data.remember_days || 0);
    const rememberDays = Number.isFinite(rememberDaysRaw) && rememberDaysRaw > 0 ? Math.floor(rememberDaysRaw) : 30;
    const maxAge = rememberDays * 24 * 60 * 60;
    if (token) {
      response.cookies.set("hs_session", token, {
        httpOnly: true,
        sameSite: "lax",
        path: "/",
        maxAge,
        secure: process.env.NODE_ENV === "production",
      });
    }
    if (userIdValue) {
      response.cookies.set("hs_user_id", String(userIdValue), {
        httpOnly: false,
        sameSite: "lax",
        path: "/",
        maxAge,
        secure: process.env.NODE_ENV === "production",
      });
    }
    return response;
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}

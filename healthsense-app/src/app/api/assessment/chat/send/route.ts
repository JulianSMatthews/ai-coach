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
    const requestedUserId = body.userId ?? getCookieValue(cookieHeader, "hs_user_id");
    const userId = resolveAssessmentUserId(requestedUserId, cookieHeader, explicitLeadToken || null);
    const textValue = String(body.text || "").trim();
    if (!textValue) {
      return NextResponse.json({ error: "text is required" }, { status: 400 });
    }

    const payload = {
      text: textValue,
      chat_mode: String(body.chat_mode || "").trim() || undefined,
      quick_reply:
        body.quick_reply && typeof body.quick_reply === "object"
          ? body.quick_reply
          : undefined,
    };
    const leadToken = explicitLeadToken || getCookieValue(cookieHeader, "hs_lead_token");
    const leadMode = (isLeadGuestUserId(requestedUserId) || (!userId && Boolean(leadToken))) && !(userId && !isLeadGuestUserId(userId));

    const base = getBaseUrl();
    if (leadMode) {
      if (!leadToken) {
        return NextResponse.json({ error: "Lead session expired. Please reopen the assessment link." }, { status: 401 });
      }
      const res = await fetch(`${base}/api/v1/public/assessment/lead-first-reply`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          lead_token: leadToken,
          text: textValue,
          quick_reply: payload.quick_reply,
        }),
        cache: "no-store",
      });
      const text = await res.text().catch(() => "");
      if (!res.ok) {
        return NextResponse.json({ error: text || "Failed to send assessment message" }, { status: res.status });
      }
      let data: Record<string, unknown> = {};
      if (text) {
        try {
          data = JSON.parse(text) as Record<string, unknown>;
        } catch {
          return NextResponse.json({ error: "Upstream returned invalid response." }, { status: 502 });
        }
      }
      const response = NextResponse.json(data);
      const sessionToken = String(data.session_token || "").trim();
      const resolvedUserId = String(data.user_id || "").trim();
      if (sessionToken && resolvedUserId) {
        const ttlSecondsRaw = Number(data.session_ttl_seconds || 0);
        const ttlSeconds = Number.isFinite(ttlSecondsRaw) && ttlSecondsRaw > 0 ? Math.floor(ttlSecondsRaw) : 60 * 60 * 3;
        response.cookies.set("hs_session", sessionToken, {
          httpOnly: true,
          sameSite: "lax",
          path: "/",
          maxAge: ttlSeconds,
          secure: process.env.NODE_ENV === "production",
        });
        response.cookies.set("hs_user_id", resolvedUserId, {
          httpOnly: false,
          sameSite: "lax",
          path: "/",
          maxAge: ttlSeconds,
          secure: process.env.NODE_ENV === "production",
        });
      }
      response.cookies.set("hs_lead_token", "", {
        httpOnly: true,
        sameSite: "lax",
        path: "/",
        maxAge: 0,
        secure: process.env.NODE_ENV === "production",
      });
      response.cookies.set("hs_lead_q1", "", {
        httpOnly: true,
        sameSite: "lax",
        path: "/",
        maxAge: 0,
        secure: process.env.NODE_ENV === "production",
      });
      return response;
    }
    if (!userId) {
      return NextResponse.json({ error: "userId is required" }, { status: 400 });
    }

    const session = getCookieValue(cookieHeader, "hs_session");
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
    };
    if (session) {
      headers["X-Session-Token"] = session;
    } else {
      Object.assign(headers, getAdminHeaders());
    }

    const url = `${base}/api/v1/users/${encodeURIComponent(String(userId))}/assessment/chat/send`;
    const res = await fetch(url, {
      method: "POST",
      headers,
      body: JSON.stringify(payload),
      cache: "no-store",
    });
    const text = await res.text().catch(() => "");
    if (!res.ok) {
      return NextResponse.json({ error: text || "Failed to send assessment message" }, { status: res.status });
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

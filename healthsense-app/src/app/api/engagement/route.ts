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

export async function POST(request: Request) {
  try {
    const body = await request.json().catch(() => ({}));
    let userId = body?.userId;
    if (!userId) {
      const cookieHeader = request.headers.get("cookie") || "";
      const match = cookieHeader.match(/(?:^|; )hs_user_id=([^;]+)/);
      userId = match ? match[1] : undefined;
    }
    if (!userId) {
      return NextResponse.json({ error: "userId is required" }, { status: 400 });
    }

    const eventType = String(body?.event_type || "").trim().toLowerCase();
    if (!["podcast_play", "podcast_complete"].includes(eventType)) {
      return NextResponse.json({ error: "event_type must be podcast_play or podcast_complete" }, { status: 400 });
    }

    const payload = {
      event_type: eventType,
      surface: body?.surface,
      podcast_id: body?.podcast_id,
      meta: body?.meta,
    };

    const base = getBaseUrl();
    const url = `${base}/api/v1/users/${userId}/engagement`;
    const cookieHeader = request.headers.get("cookie") || "";
    const sessionMatch = cookieHeader.match(/(?:^|; )hs_session=([^;]+)/);
    const session = sessionMatch ? sessionMatch[1] : null;

    const headers: Record<string, string> = {
      "Content-Type": "application/json",
    };
    if (session) {
      headers["X-Session-Token"] = session;
    } else {
      Object.assign(headers, getAdminHeaders());
    }

    const res = await fetch(url, {
      method: "POST",
      headers,
      body: JSON.stringify(payload),
      cache: "no-store",
    });
    const text = await res.text().catch(() => "");
    if (!res.ok) {
      return NextResponse.json({ error: text || "Failed to log engagement" }, { status: res.status });
    }
    if (!text) {
      return NextResponse.json({ ok: true });
    }
    return NextResponse.json(JSON.parse(text));
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}

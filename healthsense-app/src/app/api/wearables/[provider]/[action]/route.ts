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

export async function POST(
  request: Request,
  context: { params: Promise<{ provider: string; action: string }> },
) {
  try {
    const { provider, action } = await context.params;
    const actionKey = String(action || "").trim().toLowerCase();
    if (!["connect", "disconnect", "sync"].includes(actionKey)) {
      return NextResponse.json({ error: "Unsupported wearable action" }, { status: 404 });
    }

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

    const base = getBaseUrl();
    const url = `${base}/api/v1/users/${userId}/wearables/${encodeURIComponent(String(provider || "").trim().toLowerCase())}/${actionKey}`;
    const cookieHeader = request.headers.get("cookie") || "";
    const match = cookieHeader.match(/(?:^|; )hs_session=([^;]+)/);
    const session = match ? match[1] : null;
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
    };
    if (session) {
      headers["X-Session-Token"] = session;
    } else {
      Object.assign(headers, getAdminHeaders());
    }

    const payload =
      actionKey === "connect"
        ? { redirect_path: body?.redirect_path ?? `/preferences/${userId}` }
        : { trigger: body?.trigger ?? undefined };

    const res = await fetch(url, {
      method: "POST",
      headers,
      body: JSON.stringify(payload),
      cache: "no-store",
    });
    const text = await res.text().catch(() => "");
    if (!res.ok) {
      let message = text || `Failed to ${actionKey} wearable`;
      try {
        const parsed = text ? JSON.parse(text) : {};
        message = String(parsed?.detail || parsed?.error || message);
      } catch {}
      return NextResponse.json({ error: message }, { status: res.status });
    }
    try {
      return NextResponse.json(text ? JSON.parse(text) : { ok: true });
    } catch {
      return NextResponse.json({ ok: true, message: text || undefined });
    }
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}

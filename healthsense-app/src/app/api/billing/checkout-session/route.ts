import { NextResponse } from "next/server";

function getBaseUrl() {
  const base = process.env.API_BASE_URL;
  if (!base) {
    throw new Error("API_BASE_URL is not set");
  }
  return base.replace(/\/+$/, "");
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

    const payload = {
      price_id: body?.price_id,
      plan_code: body?.plan_code,
      success_path: body?.success_path,
      cancel_path: body?.cancel_path,
    };

    const base = getBaseUrl();
    const url = `${base}/api/v1/users/${userId}/billing/checkout-session`;
    const cookieHeader = request.headers.get("cookie") || "";
    const sessionMatch = cookieHeader.match(/(?:^|; )hs_session=([^;]+)/);
    const session = sessionMatch ? sessionMatch[1] : null;
    if (!session) {
      return NextResponse.json(
        {
          error:
            "Checkout is unavailable in admin preview. Open the user app session to set up subscription.",
          code: "admin_preview_read_only",
        },
        { status: 403 },
      );
    }
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
    };
    headers["X-Session-Token"] = session;

    const res = await fetch(url, {
      method: "POST",
      headers,
      body: JSON.stringify(payload),
      cache: "no-store",
    });
    const text = await res.text().catch(() => "");
    if (!res.ok) {
      let parsed: { detail?: string; error?: string } | null = null;
      try {
        parsed = text ? JSON.parse(text) : null;
      } catch {
        parsed = null;
      }
      const detail = String(parsed?.detail || parsed?.error || text || "").trim();
      const isReadOnly = detail.toLowerCase().includes("admin app preview is read-only");
      return NextResponse.json(
        {
          error: isReadOnly
            ? "Checkout is unavailable in admin preview. Open the user app session to set up subscription."
            : detail || "Failed to create checkout session",
          code: isReadOnly ? "admin_preview_read_only" : undefined,
        },
        { status: res.status },
      );
    }
    if (!text) return NextResponse.json({ ok: true });
    return NextResponse.json(JSON.parse(text));
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}

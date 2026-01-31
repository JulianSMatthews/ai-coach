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
    const body = await request.json();
    let userId = body?.userId;
    if (!userId) {
      const cookieHeader = request.headers.get("cookie") || "";
      const match = cookieHeader.match(/(?:^|; )hs_user_id=([^;]+)/);
      userId = match ? match[1] : undefined;
    }
    if (!userId) {
      return NextResponse.json({ error: "userId is required" }, { status: 400 });
    }
    const rawPassword =
      typeof body?.password === "string" ? body.password.trim() : body?.password;
    const password = rawPassword ? rawPassword : undefined;
    const payload = {
      email: body.email ?? undefined,
      note: body.note ?? undefined,
      voice: body.voice ?? undefined,
      auto_prompts: body.auto_prompts ?? undefined,
      schedule: body.schedule ?? undefined,
      text_scale: body.text_scale ?? undefined,
      training_objective: body.training_objective ?? undefined,
      preferred_channel: body.preferred_channel ?? undefined,
      marketing_opt_in: body.marketing_opt_in ?? undefined,
      password,
    };
    const base = getBaseUrl();
    const url = `${base}/api/v1/users/${userId}/preferences`;
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
    const res = await fetch(url, {
      method: "POST",
      headers,
      body: JSON.stringify(payload),
      cache: "no-store",
    });
    if (!res.ok) {
      const text = await res.text().catch(() => "");
      return NextResponse.json({ error: text || "Failed to update preferences" }, { status: res.status });
    }
    return NextResponse.json({ ok: true });
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}

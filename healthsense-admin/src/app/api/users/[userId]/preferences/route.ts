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
  context: { params: Promise<{ userId: string }> },
) {
  try {
    const { userId: rawParamId } = await context.params;
    let userId = Number(rawParamId);
    if (!Number.isFinite(userId) || userId <= 0) {
      userId = NaN;
    }
    const body = await request.json().catch(() => ({}));
    if (!Number.isFinite(userId) || userId <= 0) {
      const bodyId = Number(body?.userId);
      if (Number.isFinite(bodyId) && bodyId > 0) {
        userId = bodyId;
      }
    }
    const rawPassword = typeof body?.password === "string" ? body.password.trim() : body?.password;
    const password = rawPassword ? rawPassword : undefined;
    const payload = { password };
    const base = getBaseUrl();
    const cookieHeader = request.headers.get("cookie") || "";
    if (!Number.isFinite(userId) || userId <= 0) {
      const matchUserId = cookieHeader.match(/(?:^|; )hs_user_id=([^;]+)/);
      const cookieUserId = matchUserId ? Number(matchUserId[1]) : NaN;
      if (Number.isFinite(cookieUserId) && cookieUserId > 0) {
        userId = cookieUserId;
      }
    }
    const match = cookieHeader.match(/(?:^|; )hs_session=([^;]+)/);
    const session = match ? match[1] : null;
    if ((!Number.isFinite(userId) || userId <= 0) && session) {
      try {
        const me = await fetch(`${base}/api/v1/auth/me`, {
          headers: { "X-Session-Token": session },
          cache: "no-store",
        });
        if (me.ok) {
          const profile = await me.json();
          const fetchedId = Number(profile?.user?.id);
          if (Number.isFinite(fetchedId) && fetchedId > 0) {
            userId = fetchedId;
          }
        }
      } catch {}
    }
    if (!Number.isFinite(userId) || userId <= 0) {
      return NextResponse.json({ error: "userId is required" }, { status: 400 });
    }
    const url = `${base}/api/v1/users/${userId}/preferences`;
    const headers: Record<string, string> = { "Content-Type": "application/json" };
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
      return NextResponse.json({ error: text || "Failed to update password" }, { status: res.status });
    }
    return NextResponse.json({ ok: true });
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}

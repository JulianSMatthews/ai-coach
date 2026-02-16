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

export async function PUT(request: Request, context: { params: Promise<{ krId: string }> }) {
  try {
    const params = await context.params;
    const krId = Number(params.krId);
    if (!Number.isFinite(krId)) {
      return NextResponse.json({ error: "krId is required" }, { status: 400 });
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

    const payload = {
      actual_num: body?.actual_num,
      note: body?.note,
    };

    const base = getBaseUrl();
    const url = `${base}/api/v1/users/${userId}/krs/${krId}`;
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
      method: "PUT",
      headers,
      body: JSON.stringify(payload),
      cache: "no-store",
    });
    if (!res.ok) {
      const text = await res.text().catch(() => "");
      return NextResponse.json({ error: text || "Failed to update KR" }, { status: res.status });
    }
    const data = await res.json().catch(() => ({}));
    return NextResponse.json(data);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}

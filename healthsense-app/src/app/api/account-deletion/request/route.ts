import { NextResponse } from "next/server";

function getBaseUrl() {
  const base = process.env.API_BASE_URL;
  if (!base) {
    throw new Error("API_BASE_URL is not set");
  }
  return base.replace(/\/+$/, "");
}

function cookieValue(cookieHeader: string, name: string): string | null {
  const match = cookieHeader.match(new RegExp(`(?:^|; )${name}=([^;]+)`));
  return match ? decodeURIComponent(match[1] || "") : null;
}

export async function POST(request: Request) {
  try {
    const body = await request.json().catch(() => ({}));
    const cookieHeader = request.headers.get("cookie") || "";
    const session = cookieValue(cookieHeader, "hs_session");
    const cookieUserId = cookieValue(cookieHeader, "hs_user_id");
    const userId = String(body?.userId || cookieUserId || "").trim();

    if (!session || !userId) {
      return NextResponse.json({ error: "Please sign in before requesting account deletion." }, { status: 401 });
    }

    const res = await fetch(`${getBaseUrl()}/api/v1/users/${encodeURIComponent(userId)}/account-deletion-request`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Session-Token": session,
      },
      body: JSON.stringify({
        email: body?.email || undefined,
        reason: body?.reason || undefined,
      }),
      cache: "no-store",
    });
    const text = await res.text().catch(() => "");
    if (!res.ok) {
      return NextResponse.json({ error: text || "Failed to request account deletion." }, { status: res.status });
    }
    return NextResponse.json(text ? JSON.parse(text) : { ok: true });
  } catch (error) {
    return NextResponse.json({ error: error instanceof Error ? error.message : String(error) }, { status: 500 });
  }
}

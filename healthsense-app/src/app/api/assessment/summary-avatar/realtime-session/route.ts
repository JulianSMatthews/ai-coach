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

function buildUrl(base: string, userId: string, usePublic = false) {
  const prefix = usePublic ? "/api/v1/public/users" : "/api/v1/users";
  return `${base}${prefix}/${encodeURIComponent(userId)}/assessment/summary-avatar/realtime-session`;
}

async function forwardWithFallbacks(base: string, userId: string, session: string | null, body: string) {
  const attempts: Array<() => Promise<Response>> = [];

  if (session) {
    attempts.push(() =>
      fetch(buildUrl(base, userId, false), {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Session-Token": session,
        },
        body,
        cache: "no-store",
      }),
    );
  }

  if (process.env.ADMIN_API_TOKEN && process.env.ADMIN_USER_ID) {
    attempts.push(() =>
      fetch(buildUrl(base, userId, false), {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...getAdminHeaders(),
        },
        body,
        cache: "no-store",
      }),
    );
  }

  attempts.push(() =>
    fetch(buildUrl(base, userId, true), {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body,
      cache: "no-store",
    }),
  );

  let lastResponse: Response | null = null;
  for (const attempt of attempts) {
    const res = await attempt();
    if (res.ok) {
      return res;
    }
    lastResponse = res;
    if (res.status !== 401 && res.status !== 403 && res.status < 500) {
      return res;
    }
  }
  return lastResponse;
}

export async function POST(request: Request) {
  try {
    const body = (await request.json().catch(() => ({}))) as Record<string, unknown>;
    const userId = String(body.userId || "").replace(/[^0-9]/g, "");
    if (!userId) {
      return NextResponse.json({ error: "userId is required" }, { status: 400 });
    }

    const base = getBaseUrl();
    const cookieHeader = request.headers.get("cookie") || "";
    const sessionMatch = cookieHeader.match(/(?:^|; )hs_session=([^;]+)/);
    const session = sessionMatch ? sessionMatch[1] : null;
    const res = await forwardWithFallbacks(
      base,
      userId,
      session,
      JSON.stringify({ run_id: body.runId ?? null }),
    );
    if (!res) {
      return NextResponse.json({ error: "We couldn't start the summary video right now." }, { status: 502 });
    }

    if (!res.ok) {
      const text = await res.text().catch(() => "");
      const errorMessage =
        res.status >= 500
          ? "We couldn't start the summary video right now."
          : text || "Failed to start realtime summary avatar";
      return NextResponse.json({ error: errorMessage }, { status: res.status });
    }

    const data = await res.json();
    return NextResponse.json(data);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}

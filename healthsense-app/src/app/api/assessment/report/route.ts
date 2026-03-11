import { NextResponse } from "next/server";

function getBaseUrl() {
  const base = process.env.API_BASE_URL;
  if (!base) {
    throw new Error("API_BASE_URL is not set");
  }
  return base.replace(/\/+$/, "");
}

function buildAssessmentUrl(base: string, userId: string, runId?: string | null, usePublic = false) {
  const params = new URLSearchParams();
  if (runId) {
    params.set("run_id", runId);
  }
  const qs = params.toString();
  const prefix = usePublic ? "/api/v1/public/users" : "/api/v1/users";
  return `${base}${prefix}/${encodeURIComponent(userId)}/assessment${qs ? `?${qs}` : ""}`;
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

async function fetchAssessmentWithFallbacks(base: string, userId: string, runId?: string | null, session?: string | null) {
  const attempts: Array<() => Promise<Response>> = [];

  if (session) {
    attempts.push(() =>
      fetch(buildAssessmentUrl(base, userId, runId || null, false), {
        headers: {
          "X-Session-Token": session,
        },
        cache: "no-store",
      }),
    );
  }

  if (process.env.ADMIN_API_TOKEN && process.env.ADMIN_USER_ID) {
    attempts.push(() =>
      fetch(buildAssessmentUrl(base, userId, runId || null, false), {
        headers: getAdminHeaders(),
        cache: "no-store",
      }),
    );
  }

  attempts.push(() =>
    fetch(buildAssessmentUrl(base, userId, runId || null, true), {
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

export async function GET(request: Request) {
  try {
    const { searchParams } = new URL(request.url);
    const userId = String(searchParams.get("userId") || "").replace(/[^0-9]/g, "");
    const runId = String(searchParams.get("runId") || "").replace(/[^0-9]/g, "");

    if (!userId) {
      return NextResponse.json({ error: "userId is required" }, { status: 400 });
    }

    const base = getBaseUrl();
    const cookieHeader = request.headers.get("cookie") || "";
    const sessionMatch = cookieHeader.match(/(?:^|; )hs_session=([^;]+)/);
    const session = sessionMatch ? sessionMatch[1] : null;
    const res = await fetchAssessmentWithFallbacks(base, userId, runId || null, session);

    if (!res.ok) {
      const text = await res.text().catch(() => "");
      const errorMessage =
        res.status >= 500
          ? "We couldn't load the coaching plan right now."
          : text || "Failed to load assessment report";
      return NextResponse.json({ error: errorMessage }, { status: res.status });
    }

    const data = await res.json();
    return NextResponse.json(data);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}

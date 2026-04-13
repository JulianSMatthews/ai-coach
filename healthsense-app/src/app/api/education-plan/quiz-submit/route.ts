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

function normalizeReportUrl(value: unknown, base: string): string | null {
  const raw = String(value || "").trim();
  if (!raw) return null;
  if (raw.startsWith("/reports/")) {
    return `${base}${raw}`;
  }
  if (raw.startsWith("reports/")) {
    return `${base}/${raw}`;
  }
  if (raw.startsWith("content/")) {
    return `${base}/reports/${raw}`;
  }
  return raw;
}

function normalizeEducationPlanMedia(data: Record<string, unknown>, base: string) {
  const lesson = data.lesson && typeof data.lesson === "object" ? data.lesson as Record<string, unknown> : null;
  const content = lesson?.content && typeof lesson.content === "object" ? lesson.content as Record<string, unknown> : null;
  if (!content) return data;
  for (const key of ["video_url", "podcast_url", "poster_url"]) {
    content[key] = normalizeReportUrl(content[key], base);
  }
  const avatar = content.avatar && typeof content.avatar === "object" ? content.avatar as Record<string, unknown> : null;
  if (avatar) {
    for (const key of ["url", "poster_url", "summary_url"]) {
      avatar[key] = normalizeReportUrl(avatar[key], base);
    }
  }
  return data;
}

export async function POST(request: Request) {
  try {
    const body = (await request.json().catch(() => ({}))) as Record<string, unknown>;
    const cookieHeader = request.headers.get("cookie") || "";
    const userId = String(body.userId || getCookieValue(cookieHeader, "hs_user_id") || "").trim();
    if (!userId) {
      return NextResponse.json({ error: "userId is required" }, { status: 400 });
    }
    const base = getBaseUrl();
    const session = getCookieValue(cookieHeader, "hs_session");
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
    };
    if (session) {
      headers["X-Session-Token"] = session;
    } else {
      Object.assign(headers, getAdminHeaders());
    }
    const res = await fetch(`${base}/api/v1/users/${encodeURIComponent(userId)}/education-plan/quiz-submit`, {
      method: "POST",
      headers,
      body: JSON.stringify(body),
      cache: "no-store",
    });
    const text = await res.text().catch(() => "");
    if (!res.ok) {
      return NextResponse.json({ error: text || "Failed to submit education quiz" }, { status: res.status });
    }
    const data = (text ? JSON.parse(text) : {}) as Record<string, unknown>;
    return NextResponse.json(normalizeEducationPlanMedia(data, base));
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}

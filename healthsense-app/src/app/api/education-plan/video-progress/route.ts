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

function normalizeLessonMedia(lesson: unknown, base: string) {
  const lessonRecord = lesson && typeof lesson === "object" ? lesson as Record<string, unknown> : null;
  const content = lessonRecord?.content && typeof lessonRecord.content === "object" ? lessonRecord.content as Record<string, unknown> : null;
  if (!content) return;
  for (const key of ["video_url", "podcast_url", "poster_url"]) {
    content[key] = normalizeReportUrl(content[key], base);
  }
  const avatar = content.avatar && typeof content.avatar === "object" ? content.avatar as Record<string, unknown> : null;
  if (avatar) {
    for (const key of ["url", "video_url", "result_url", "resultUrl", "poster_url", "summary_url"]) {
      avatar[key] = normalizeReportUrl(avatar[key], base);
    }
  }
}

function normalizeEducationPlanMedia(data: Record<string, unknown>, base: string) {
  normalizeLessonMedia(data.lesson, base);
  normalizeLessonMedia(data.submitted_lesson, base);
  for (const lesson of Array.isArray(data.lessons) ? data.lessons : []) {
    normalizeLessonMedia(lesson, base);
  }
  const journey = data.journey && typeof data.journey === "object" ? data.journey as Record<string, unknown> : null;
  for (const programme of Array.isArray(journey?.programmes) ? journey.programmes : []) {
    const programmeRecord = programme && typeof programme === "object" ? programme as Record<string, unknown> : null;
    for (const lesson of Array.isArray(programmeRecord?.lessons) ? programmeRecord.lessons : []) {
      normalizeLessonMedia(lesson, base);
    }
  }
  const catalog = data.explore_catalog && typeof data.explore_catalog === "object" ? data.explore_catalog as Record<string, unknown> : null;
  for (const pillar of Array.isArray(catalog?.pillars) ? catalog.pillars : []) {
    const pillarRecord = pillar && typeof pillar === "object" ? pillar as Record<string, unknown> : null;
    for (const concept of Array.isArray(pillarRecord?.concepts) ? pillarRecord.concepts : []) {
      const conceptRecord = concept && typeof concept === "object" ? concept as Record<string, unknown> : null;
      for (const lesson of Array.isArray(conceptRecord?.lessons) ? conceptRecord.lessons : []) {
        normalizeLessonMedia(lesson, base);
      }
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
    const res = await fetch(`${base}/api/v1/users/${encodeURIComponent(userId)}/education-plan/video-progress`, {
      method: "POST",
      headers,
      body: JSON.stringify(body),
      cache: "no-store",
    });
    const text = await res.text().catch(() => "");
    if (!res.ok) {
      return NextResponse.json({ error: text || "Failed to save education video progress" }, { status: res.status });
    }
    const data = (text ? JSON.parse(text) : {}) as Record<string, unknown>;
    return NextResponse.json(normalizeEducationPlanMedia(data, base));
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}

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

function parseUpstreamError(text: string, fallback: string) {
  const raw = String(text || "").trim();
  if (!raw) return fallback;
  try {
    const parsed = JSON.parse(raw) as { error?: unknown; detail?: unknown };
    const message = parsed.detail || parsed.error;
    if (message) return String(message);
  } catch {
    // Keep raw text when the upstream response is not JSON.
  }
  return raw;
}

function quizSubmitUpstreamError(text: string, status: number) {
  const parsed = parseUpstreamError(text, "");
  const normalized = parsed.trim().toLowerCase();
  if (!normalized || normalized === "internal server error") {
    return `Quiz submit upstream failed with status ${status}${text ? `: ${String(text).trim()}` : ""}`;
  }
  return parsed;
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

const RETRYABLE_QUIZ_SUBMIT_STATUSES = new Set([408, 409, 425, 429, 500, 502, 503, 504]);

async function submitQuizUpstream(
  url: string,
  headers: Record<string, string>,
  body: Record<string, unknown>,
) {
  let lastResponse: Response | null = null;
  let lastError: unknown = null;
  for (let attempt = 0; attempt < 2; attempt += 1) {
    try {
      const response = await fetch(url, {
        method: "POST",
        headers,
        body: JSON.stringify(body),
        cache: "no-store",
      });
      lastResponse = response;
      if (!RETRYABLE_QUIZ_SUBMIT_STATUSES.has(response.status) || attempt === 1) {
        return response;
      }
      await response.arrayBuffer().catch(() => undefined);
    } catch (error) {
      lastError = error;
      if (attempt === 1) throw error;
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  if (lastResponse) return lastResponse;
  throw lastError instanceof Error ? lastError : new Error("Quiz submission failed before receiving a response.");
}

export async function POST(request: Request) {
  try {
    const body = (await request.json().catch(() => ({}))) as Record<string, unknown>;
    const cookieHeader = request.headers.get("cookie") || "";
    const session = getCookieValue(cookieHeader, "hs_session");
    const cookieUserId = String(getCookieValue(cookieHeader, "hs_user_id") || "").trim();
    const bodyUserId = String(body.userId || "").trim();
    const userId = (session && cookieUserId ? cookieUserId : bodyUserId || cookieUserId).trim();
    if (!userId) {
      return NextResponse.json({ error: "userId is required" }, { status: 400 });
    }
    const base = getBaseUrl();
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
    };
    if (session) {
      headers["X-Session-Token"] = session;
    } else {
      Object.assign(headers, getAdminHeaders());
    }
    const submissionId = String(body.submission_id || "").trim() || crypto.randomUUID();
    headers["X-Quiz-Submission-Id"] = submissionId;
    const res = await submitQuizUpstream(
      `${base}/api/v1/users/${encodeURIComponent(userId)}/education-plan/quiz-submit`,
      headers,
      { ...body, userId, submission_id: submissionId },
    );
    const text = await res.text().catch(() => "");
    if (!res.ok) {
      return NextResponse.json({ error: quizSubmitUpstreamError(text, res.status) }, { status: res.status });
    }
    const data = (text ? JSON.parse(text) : {}) as Record<string, unknown>;
    return NextResponse.json(normalizeEducationPlanMedia(data, base));
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}

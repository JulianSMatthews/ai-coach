import { NextResponse } from "next/server";

const DEFAULT_MAX_AGE_SECONDS = 60 * 30;
const FALLBACK_PUBLIC_APP_ORIGIN = "https://app.healthsense.coach";

function normalizeOrigin(raw: string | null | undefined): string | null {
  const value = String(raw || "").trim();
  if (!value) return null;
  try {
    const parsed = new URL(value.startsWith("http://") || value.startsWith("https://") ? value : `https://${value}`);
    return parsed.origin;
  } catch {
    return null;
  }
}

function isLocalOrigin(origin: string | null | undefined): boolean {
  const value = String(origin || "").trim();
  if (!value) return false;
  try {
    const parsed = new URL(value);
    const host = parsed.hostname.toLowerCase();
    return host === "localhost" || host === "127.0.0.1" || host === "0.0.0.0" || host.endsWith(".local");
  } catch {
    return false;
  }
}

function resolvePublicAppOrigin(request: Request): string {
  const nodeEnv = (process.env.NODE_ENV || "").toLowerCase();
  const isProd = nodeEnv === "production";
  const envCandidates = [
    process.env.NEXT_PUBLIC_HSAPP_BASE_URL,
    process.env.NEXT_PUBLIC_APP_BASE_URL,
    process.env.HSAPP_PUBLIC_URL,
    process.env.APP_BASE_URL,
  ];
  for (const raw of envCandidates) {
    const normalized = normalizeOrigin(raw);
    if (!normalized) continue;
    if (isProd && isLocalOrigin(normalized)) continue;
    return normalized;
  }

  const proto = (request.headers.get("x-forwarded-proto") || "").trim();
  const host = (request.headers.get("x-forwarded-host") || request.headers.get("host") || "").trim();
  if (host) {
    const normalized = normalizeOrigin(`${proto || "https"}://${host}`);
    if (normalized && (!isProd || !isLocalOrigin(normalized))) {
      return normalized;
    }
  }

  const requestOrigin = normalizeOrigin(request.url);
  if (requestOrigin && (!isProd || !isLocalOrigin(requestOrigin))) {
    return requestOrigin;
  }
  return FALLBACK_PUBLIC_APP_ORIGIN;
}

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const sessionToken = (searchParams.get("session_token") || "").trim();
  const userIdRaw = (searchParams.get("user_id") || "").trim();
  const nextRaw = (searchParams.get("next") || "").trim();

  if (!sessionToken) {
    return NextResponse.redirect(new URL("/login", request.url));
  }

  const userId = String(Number(userIdRaw || "0") || "");
  const nextPath =
    nextRaw && nextRaw.startsWith("/") && !nextRaw.startsWith("//")
      ? nextRaw
      : userId
        ? `/progress/${userId}`
        : "/login";

  const publicOrigin = resolvePublicAppOrigin(request);
  const response = NextResponse.redirect(new URL(nextPath, publicOrigin));
  response.cookies.set("hs_session", sessionToken, {
    httpOnly: true,
    sameSite: "lax",
    path: "/",
    maxAge: DEFAULT_MAX_AGE_SECONDS,
    secure: process.env.NODE_ENV === "production",
  });
  if (userId) {
    response.cookies.set("hs_user_id", userId, {
      httpOnly: false,
      sameSite: "lax",
      path: "/",
      maxAge: DEFAULT_MAX_AGE_SECONDS,
      secure: process.env.NODE_ENV === "production",
    });
  }
  return response;
}

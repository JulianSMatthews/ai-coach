import { NextResponse } from "next/server";

function getBaseUrl() {
  const base = process.env.API_BASE_URL;
  if (!base) {
    throw new Error("API_BASE_URL is not set");
  }
  return base.replace(/\/+$/, "");
}

function toBool(value: string | null | undefined): boolean {
  const token = String(value || "").trim().toLowerCase();
  return token === "1" || token === "true" || token === "yes" || token === "on";
}

export async function GET(request: Request) {
  const reqUrl = new URL(request.url);
  const fallback = new URL("/login", reqUrl.origin);
  try {
    const base = getBaseUrl();
    const leadKey = (reqUrl.searchParams.get("k") || "").trim();
    const campaign = (reqUrl.searchParams.get("campaign") || reqUrl.searchParams.get("utm_campaign") || "").trim();
    const source = (reqUrl.searchParams.get("source") || reqUrl.searchParams.get("utm_source") || "instagram").trim();

    const utm: Record<string, string> = {};
    ["utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content"].forEach((key) => {
      const value = (reqUrl.searchParams.get(key) || "").trim();
      if (value) utm[key] = value;
    });

    const payload = {
      lead_key: leadKey || undefined,
      source,
      campaign: campaign || undefined,
      utm,
    };

    const upstream = await fetch(`${base}/api/v1/public/assessment/lead-start`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      cache: "no-store",
    });
    const text = await upstream.text().catch(() => "");
    if (!upstream.ok || !text.trim()) {
      const fail = new URL("/login", reqUrl.origin);
      fail.searchParams.set("lead", "failed");
      return NextResponse.redirect(fail);
    }

    let data: Record<string, unknown>;
    try {
      data = JSON.parse(text) as Record<string, unknown>;
    } catch {
      const fail = new URL("/login", reqUrl.origin);
      fail.searchParams.set("lead", "invalid");
      return NextResponse.redirect(fail);
    }

    const sessionToken = String(data.session_token || "").trim();
    const userId = String(data.user_id || "").trim();
    const nextPathRaw = String(data.next_path || "").trim();
    const nextPath = nextPathRaw.startsWith("/") && !nextPathRaw.startsWith("//") ? nextPathRaw : `/assessment/${userId}/chat?autostart=1&lead=1`;
    if (!sessionToken || !userId) {
      const fail = new URL("/login", reqUrl.origin);
      fail.searchParams.set("lead", "missing");
      return NextResponse.redirect(fail);
    }

    const ttlSecondsRaw = Number(data.session_ttl_seconds || 0);
    const ttlSeconds = Number.isFinite(ttlSecondsRaw) && ttlSecondsRaw > 0 ? Math.floor(ttlSecondsRaw) : 60 * 60 * 3;

    const redirectUrl = new URL(nextPath, reqUrl.origin);
    if (toBool(reqUrl.searchParams.get("debug"))) {
      redirectUrl.searchParams.set("lead_debug", "1");
    }
    const response = NextResponse.redirect(redirectUrl);
    response.cookies.set("hs_session", sessionToken, {
      httpOnly: true,
      sameSite: "lax",
      path: "/",
      maxAge: ttlSeconds,
      secure: process.env.NODE_ENV === "production",
    });
    response.cookies.set("hs_user_id", userId, {
      httpOnly: false,
      sameSite: "lax",
      path: "/",
      maxAge: ttlSeconds,
      secure: process.env.NODE_ENV === "production",
    });
    return response;
  } catch {
    return NextResponse.redirect(fallback);
  }
}
